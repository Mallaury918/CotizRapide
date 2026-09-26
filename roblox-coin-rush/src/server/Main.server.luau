-- Point d'entrée serveur de Coin Rush.
-- Toute la logique de gain / dépense est ici : le client ne fait qu'envoyer des demandes.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = require(Shared:WaitForChild("Config"))
local Economy = require(Shared:WaitForChild("Economy"))

local DataService = require(script.Parent:WaitForChild("DataService"))
local MonetizationService = require(script.Parent:WaitForChild("MonetizationService"))
local World = require(script.Parent:WaitForChild("World"))

-- Remotes -------------------------------------------------------------------

local remotes = Instance.new("Folder")
remotes.Name = "Remotes"
local function newRemote(name: string): RemoteEvent
	local remote = Instance.new("RemoteEvent")
	remote.Name = name
	remote.Parent = remotes
	return remote
end
local ClickRemote = newRemote("Click")
local BuyUpgradeRemote = newRemote("BuyUpgrade")
local RebirthRemote = newRemote("Rebirth")
local StateRemote = newRemote("State")
local NotifyRemote = newRemote("Notify")
remotes.Parent = ReplicatedStorage

-- Helpers -------------------------------------------------------------------

local function getFlags(player: Player, data)
	return {
		DoubleCoins = player:GetAttribute("DoubleCoins") == true,
		VIP = player:GetAttribute("VIP") == true,
		Boost = data.BoostEndsAt > os.time(),
	}
end

local function notify(player: Player, text: string, kind: string?)
	NotifyRemote:FireClient(player, text, kind or "info")
end

local function applyWalkSpeed(player: Player)
	local data = DataService.get(player)
	local humanoid = player.Character and player.Character:FindFirstChildOfClass("Humanoid")
	if data and humanoid then
		humanoid.WalkSpeed = Economy.getWalkSpeed(data, player:GetAttribute("VIP") == true)
	end
end

local function pushState(player: Player)
	local data = DataService.get(player)
	if not data then
		return
	end
	local leaderstats = player:FindFirstChild("leaderstats")
	if leaderstats then
		leaderstats.Coins.Value = math.floor(data.Coins)
		leaderstats.Rebirths.Value = data.Rebirths
	end
	StateRemote:FireClient(player, {
		Coins = data.Coins,
		Rebirths = data.Rebirths,
		Upgrades = data.Upgrades,
		BoostEndsAt = data.BoostEndsAt,
		Multiplier = Economy.getMultiplier(data, getFlags(player, data)),
	})
end

local function onPlayerChanged(player: Player)
	applyWalkSpeed(player)
	pushState(player)
end

local function addCoins(player: Player, baseAmount: number): number
	local data = DataService.get(player)
	if not data then
		return 0
	end
	local amount = math.max(1, math.floor(baseAmount * Economy.getMultiplier(data, getFlags(player, data))))
	data.Coins += amount
	data.TotalCoins += amount
	pushState(player)
	return amount
end

-- Joueurs -------------------------------------------------------------------

local lastClick = {} -- [Player] = os.clock()

local function onPlayerAdded(player: Player)
	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Parent = leaderstats
	local rebirths = Instance.new("IntValue")
	rebirths.Name = "Rebirths"
	rebirths.Parent = leaderstats
	leaderstats.Parent = player

	player.CharacterAdded:Connect(function(character)
		character:WaitForChild("Humanoid")
		applyWalkSpeed(player)
	end)

	local data = DataService.load(player)
	if not data then
		return
	end

	MonetizationService.refreshPasses(player)
	-- Un pass acheté ailleurs (site web) ou pendant la partie : on met à jour.
	for key in Config.GamePasses do
		player:GetAttributeChangedSignal(key):Connect(function()
			onPlayerChanged(player)
		end)
	end

	onPlayerChanged(player)
	notify(player, "Bienvenue dans Coin Rush ! Ramasse les pièces et clique pour devenir riche 💰")
end

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end

Players.PlayerRemoving:Connect(function(player)
	lastClick[player] = nil
	DataService.release(player)
end)

-- Actions des joueurs --------------------------------------------------------

ClickRemote.OnServerEvent:Connect(function(player)
	local data = DataService.get(player)
	if not data then
		return
	end
	local now = os.clock()
	if now - (lastClick[player] or 0) < Config.ClickCooldown then
		return -- trop rapide : autoclicker externe
	end
	lastClick[player] = now
	addCoins(player, Economy.getClickValue(data))
end)

BuyUpgradeRemote.OnServerEvent:Connect(function(player, upgradeId)
	local data = DataService.get(player)
	if not data or type(upgradeId) ~= "string" or not Config.Upgrades[upgradeId] then
		return
	end
	local level = data.Upgrades[upgradeId]
	if Economy.isMaxed(upgradeId, level) then
		notify(player, "Niveau maximum atteint !", "error")
		return
	end
	local cost = Economy.getUpgradeCost(upgradeId, level)
	if data.Coins < cost then
		notify(player, "Pas assez de pièces ! Il en manque " .. Economy.formatNumber(cost - data.Coins), "error")
		return
	end
	data.Coins -= cost
	data.Upgrades[upgradeId] = level + 1
	onPlayerChanged(player)
end)

RebirthRemote.OnServerEvent:Connect(function(player)
	local data = DataService.get(player)
	if not data then
		return
	end
	local cost = Economy.getRebirthCost(data.Rebirths)
	if data.Coins < cost then
		notify(player, "Il te faut " .. Economy.formatNumber(cost) .. " pièces pour renaître.", "error")
		return
	end
	data.Coins = 0
	for upgradeId in data.Upgrades do
		data.Upgrades[upgradeId] = 0
	end
	data.Rebirths += 1
	onPlayerChanged(player)
	notify(player, string.format("Renaissance %d ! Gains x%.1f permanents 🔥", data.Rebirths, 1 + data.Rebirths * Config.Rebirth.BonusPerRebirth), "purchase")
	task.spawn(DataService.save, player)
end)

-- Boucles --------------------------------------------------------------------

MonetizationService.init({
	onPlayerChanged = onPlayerChanged,
	notify = notify,
})

World.buildMap()
World.startCoinSpawner(function(player, multiplier)
	local data = DataService.get(player)
	if data then
		addCoins(player, Economy.getPickupValue(data) * multiplier)
	end
end)

-- Auto-Clicker (Game Pass)
task.spawn(function()
	while true do
		task.wait(Config.AutoClickInterval)
		for _, player in Players:GetPlayers() do
			local data = DataService.get(player)
			if data and player:GetAttribute("AutoClicker") then
				addCoins(player, Economy.getClickValue(data))
			end
		end
	end
end)

-- Fin des boosts : on prévient le client pour mettre à jour le multiplicateur
task.spawn(function()
	while true do
		task.wait(1)
		for _, player in Players:GetPlayers() do
			local data = DataService.get(player)
			if data then
				local active = data.BoostEndsAt > os.time()
				local wasActive = player:GetAttribute("BoostActive") == true
				if wasActive ~= active then
					player:SetAttribute("BoostActive", active)
					pushState(player)
					if wasActive then
						notify(player, "Ton boost x3 est terminé.")
					end
				end
			end
		end
	end
end)
