-- Achats Robux : Game Passes (permanents) et Produits de développeur (consommables).
-- ProcessReceipt suit la méthode recommandée par Roblox : on ne répond
-- "PurchaseGranted" qu'une fois l'achat crédité ET sauvegardé, et chaque
-- reçu n'est crédité qu'une seule fois.

local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
local DataService = require(script.Parent:WaitForChild("DataService"))

local MonetizationService = {}

local onPlayerChanged = function(_player: Player) end
local notify = function(_player: Player, _text: string, _kind: string?) end

local passKeyById = {}
for key, pass in Config.GamePasses do
	if pass.Id ~= 0 then
		passKeyById[pass.Id] = key
	end
end

local productKeyById = {}
for key, product in Config.Products do
	if product.Id ~= 0 then
		productKeyById[product.Id] = key
	end
end

-- Ce que chaque produit donne. Renvoie le message affiché au joueur.
local productHandlers = {}

local function grantCoins(product)
	return function(_player, data)
		local amount = product.Coins * (data.Rebirths + 1)
		data.Coins += amount
		data.TotalCoins += amount
		return string.format("+%d pièces ! Merci pour ton soutien 💛", amount)
	end
end

productHandlers.SmallCoins = grantCoins(Config.Products.SmallCoins)
productHandlers.BigCoins = grantCoins(Config.Products.BigCoins)
productHandlers.HugeCoins = grantCoins(Config.Products.HugeCoins)

productHandlers.Boost = function(_player, data)
	local now = os.time()
	data.BoostEndsAt = math.max(now, data.BoostEndsAt) + Config.Products.Boost.BoostSeconds
	return "Boost x3 activé ! ⚡"
end

local function processReceipt(receipt)
	local player = Players:GetPlayerByUserId(receipt.PlayerId)
	if not player then
		-- Le joueur est parti : Roblox relancera l'achat à sa prochaine connexion.
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local data = DataService.waitForData(player, 15)
	if not data then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	if DataService.hasReceipt(data, receipt.PurchaseId) then
		return Enum.ProductPurchaseDecision.PurchaseGranted
	end

	local key = productKeyById[receipt.ProductId]
	local handler = key and productHandlers[key]
	if not handler then
		warn("[Monetization] Produit inconnu :", receipt.ProductId)
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local ok, message = pcall(handler, player, data)
	if not ok then
		warn("[Monetization] Erreur en créditant l'achat :", message)
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end
	DataService.addReceipt(data, receipt.PurchaseId)

	onPlayerChanged(player)
	notify(player, message, "purchase")

	-- Si la sauvegarde échoue, l'achat reste crédité en mémoire (avec son reçu) et
	-- sera sauvegardé plus tard ; Roblox le représentera, sans double crédit.
	if DataService.save(player) then
		return Enum.ProductPurchaseDecision.PurchaseGranted
	end
	return Enum.ProductPurchaseDecision.NotProcessedYet
end

function MonetizationService.refreshPasses(player: Player)
	for key, pass in Config.GamePasses do
		if pass.Id ~= 0 and not player:GetAttribute(key) then
			local ok, owns = pcall(function()
				return MarketplaceService:UserOwnsGamePassAsync(player.UserId, pass.Id)
			end)
			if ok and owns then
				player:SetAttribute(key, true)
			elseif not ok then
				warn("[Monetization] Vérification du pass échouée :", key, owns)
			end
		end
	end
end

function MonetizationService.init(callbacks)
	onPlayerChanged = callbacks.onPlayerChanged or onPlayerChanged
	notify = callbacks.notify or notify

	MarketplaceService.ProcessReceipt = processReceipt

	MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player, passId, purchased)
		local key = passKeyById[passId]
		if purchased and key then
			player:SetAttribute(key, true)
			onPlayerChanged(player)
			notify(player, Config.GamePasses[key].Name .. " débloqué ! Merci 💛", "purchase")
		end
	end)
end

return MonetizationService
