-- Sauvegarde des joueurs (DataStore) : chargement avec réessais,
-- sauvegarde automatique, à la déconnexion et à la fermeture du serveur.

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

local STORE_NAME = "CoinRush_PlayerData_v1"
local AUTOSAVE_INTERVAL = 120
local MAX_RECEIPTS = 100 -- derniers achats Robux mémorisés (anti double-crédit)

local DataService = {}

local profiles = {} -- [Player] = data
local canSave = {} -- [Player] = bool

local store = nil
do
	local ok, err = pcall(function()
		store = DataStoreService:GetDataStore(STORE_NAME)
	end)
	if not ok then
		warn("[DataService] DataStore indisponible :", err)
	end
end

local function defaultData()
	return {
		Coins = 0,
		TotalCoins = 0,
		Rebirths = 0,
		Upgrades = {
			ClickPower = 0,
			CoinValue = 0,
			WalkSpeed = 0,
		},
		BoostEndsAt = 0,
		Receipts = {},
	}
end

-- Ajoute les champs manquants (utile quand tu ajoutes des stats dans une mise à jour).
local function reconcile(data)
	for key, value in defaultData() do
		if data[key] == nil then
			data[key] = value
		elseif type(value) == "table" and type(data[key]) == "table" then
			for subKey, subValue in value do
				if data[key][subKey] == nil then
					data[key][subKey] = subValue
				end
			end
		end
	end
	return data
end

local function withRetries(label: string, callback)
	for attempt = 1, 3 do
		local ok, result = pcall(callback)
		if ok then
			return true, result
		end
		warn(string.format("[DataService] %s échoué (essai %d/3) : %s", label, attempt, tostring(result)))
		if attempt < 3 then
			task.wait(2 ^ attempt)
		end
	end
	return false, nil
end

local function keyFor(player: Player): string
	return "Player_" .. player.UserId
end

function DataService.load(player: Player)
	if not store then
		profiles[player] = defaultData()
		canSave[player] = false
		return profiles[player]
	end

	local ok, stored = withRetries("Chargement de " .. player.Name, function()
		return store:GetAsync(keyFor(player))
	end)

	if not ok then
		if RunService:IsStudio() then
			-- En Studio sans "Enable Studio Access to API Services" : on joue sans sauvegarde.
			warn("[DataService] Mode Studio : données non sauvegardées pour " .. player.Name)
			profiles[player] = defaultData()
			canSave[player] = false
			return profiles[player]
		end
		-- En ligne : on ne laisse pas jouer avec des données vides (sinon on écraserait la vraie sauvegarde).
		player:Kick("Impossible de charger ta sauvegarde. Reviens dans une minute !")
		return nil
	end

	if player.Parent == nil then
		return nil -- parti pendant le chargement
	end

	profiles[player] = reconcile(type(stored) == "table" and stored or defaultData())
	canSave[player] = true
	return profiles[player]
end

function DataService.get(player: Player)
	return profiles[player]
end

function DataService.waitForData(player: Player, timeout: number)
	local deadline = os.clock() + timeout
	while not profiles[player] and player.Parent ~= nil and os.clock() < deadline do
		task.wait(0.1)
	end
	return profiles[player]
end

function DataService.save(player: Player): boolean
	local data = profiles[player]
	if not data or not canSave[player] or not store then
		return false
	end
	local ok = withRetries("Sauvegarde de " .. player.Name, function()
		store:UpdateAsync(keyFor(player), function()
			return data
		end)
	end)
	return ok
end

function DataService.hasReceipt(data, purchaseId: string): boolean
	return table.find(data.Receipts, purchaseId) ~= nil
end

function DataService.addReceipt(data, purchaseId: string)
	table.insert(data.Receipts, purchaseId)
	while #data.Receipts > MAX_RECEIPTS do
		table.remove(data.Receipts, 1)
	end
end

function DataService.release(player: Player)
	DataService.save(player)
	profiles[player] = nil
	canSave[player] = nil
end

-- Sauvegarde automatique
task.spawn(function()
	while true do
		task.wait(AUTOSAVE_INTERVAL)
		for _, player in Players:GetPlayers() do
			task.spawn(DataService.save, player)
		end
	end
end)

-- Sauvegarde de tout le monde quand le serveur s'arrête
game:BindToClose(function()
	local pending = 0
	for player in profiles do
		pending += 1
		task.spawn(function()
			DataService.save(player)
			pending -= 1
		end)
	end
	local deadline = os.clock() + 25
	while pending > 0 and os.clock() < deadline do
		task.wait(0.1)
	end
end)

return DataService
