-- Interface du joueur : compteur, bouton de clic, améliorations, boutique Robux, renaissance.
-- Tout est construit en code : rien à dessiner dans Studio.

local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local player = Players.LocalPlayer
local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = require(Shared:WaitForChild("Config"))
local Economy = require(Shared:WaitForChild("Economy"))
local Remotes = ReplicatedStorage:WaitForChild("Remotes")

local COLORS = {
	Panel = Color3.fromRGB(30, 32, 48),
	PanelLight = Color3.fromRGB(46, 49, 72),
	Text = Color3.fromRGB(255, 255, 255),
	Muted = Color3.fromRGB(185, 190, 215),
	Gold = Color3.fromRGB(255, 200, 40),
	Green = Color3.fromRGB(60, 200, 110),
	Red = Color3.fromRGB(230, 70, 80),
	Blue = Color3.fromRGB(70, 140, 255),
	Robux = Color3.fromRGB(0, 176, 111),
	Purple = Color3.fromRGB(160, 90, 255),
	Disabled = Color3.fromRGB(90, 92, 110),
}

local state = nil -- dernier état reçu du serveur
local refreshers = {} -- fonctions appelées à chaque nouvel état

-- Helpers UI -----------------------------------------------------------------

local function create(className: string, props, children)
	local inst = Instance.new(className)
	for key, value in props do
		if key ~= "Parent" then
			inst[key] = value
		end
	end
	for _, child in children or {} do
		child.Parent = inst
	end
	inst.Parent = props.Parent
	return inst
end

local function corner(radius: number?)
	return create("UICorner", { CornerRadius = UDim.new(0, radius or 12) })
end

local function stroke(color: Color3, thickness: number?)
	return create("UIStroke", {
		Color = color,
		Thickness = thickness or 2,
		ApplyStrokeMode = Enum.ApplyStrokeMode.Border,
	})
end

local function label(props)
	props.BackgroundTransparency = 1
	props.Font = props.Font or Enum.Font.GothamBold
	props.TextColor3 = props.TextColor3 or COLORS.Text
	props.TextScaled = props.TextScaled ~= false
	local maxText = props.MaxText or 28
	props.MaxText = nil
	return create("TextLabel", props, { create("UITextSizeConstraint", { MaxTextSize = maxText }) })
end

local function button(props)
	props.Font = props.Font or Enum.Font.GothamBlack
	props.TextColor3 = props.TextColor3 or COLORS.Text
	props.TextScaled = true
	props.AutoButtonColor = true
	local maxText = props.MaxText or 22
	props.MaxText = nil
	return create("TextButton", props, {
		corner(10),
		create("UITextSizeConstraint", { MaxTextSize = maxText }),
		create("UIPadding", { PaddingLeft = UDim.new(0, 6), PaddingRight = UDim.new(0, 6) }),
	})
end

local function pop(guiObject: GuiObject)
	local scale = guiObject:FindFirstChildOfClass("UIScale") or create("UIScale", { Parent = guiObject })
	scale.Scale = 0.9
	TweenService:Create(scale, TweenInfo.new(0.15, Enum.EasingStyle.Back), { Scale = 1 }):Play()
end

-- Écran principal --------------------------------------------------------------

local gui = create("ScreenGui", {
	Name = "CoinRushUI",
	ResetOnSpawn = false,
	ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
	Parent = player:WaitForChild("PlayerGui"),
})

-- Compteur de pièces
local topBar = create("Frame", {
	AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.new(0.5, 0, 0, 8),
	Size = UDim2.new(0, 300, 0, 74),
	BackgroundColor3 = COLORS.Panel,
	BackgroundTransparency = 0.1,
	Parent = gui,
}, { corner(16), stroke(COLORS.Gold, 3) })

local coinsLabel = label({
	Text = "💰 0",
	Size = UDim2.new(1, -16, 0.6, 0),
	Position = UDim2.new(0, 8, 0, 4),
	TextColor3 = COLORS.Gold,
	Font = Enum.Font.GothamBlack,
	MaxText = 36,
	Parent = topBar,
})

local infoLabel = label({
	Text = "Gains x1",
	Size = UDim2.new(1, -16, 0.32, 0),
	Position = UDim2.new(0, 8, 0.64, 0),
	TextColor3 = COLORS.Muted,
	Font = Enum.Font.GothamMedium,
	MaxText = 18,
	Parent = topBar,
})

-- Bouton de clic
local clickButton = button({
	Text = "CLIQUE !",
	AnchorPoint = Vector2.new(0.5, 1),
	Position = UDim2.new(0.5, 0, 1, -24),
	Size = UDim2.new(0, 230, 0, 76),
	BackgroundColor3 = COLORS.Gold,
	TextColor3 = Color3.fromRGB(60, 40, 0),
	MaxText = 32,
	Parent = gui,
})
stroke(Color3.fromRGB(150, 100, 0), 3).Parent = clickButton

-- Notifications
local toastHolder = create("Frame", {
	AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.new(0.5, 0, 0, 92),
	Size = UDim2.new(0, 420, 0, 200),
	BackgroundTransparency = 1,
	Parent = gui,
}, {
	create("UIListLayout", {
		Padding = UDim.new(0, 6),
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		SortOrder = Enum.SortOrder.LayoutOrder,
	}),
})

local function toast(text: string, kind: string?)
	local color = kind == "error" and COLORS.Red or kind == "purchase" and COLORS.Green or COLORS.Blue
	local frame = create("Frame", {
		Size = UDim2.new(1, 0, 0, 40),
		BackgroundColor3 = COLORS.Panel,
		Parent = toastHolder,
	}, { corner(10), stroke(color, 2) })
	label({
		Text = text,
		Size = UDim2.new(1, -16, 1, -8),
		Position = UDim2.new(0, 8, 0, 4),
		Font = Enum.Font.GothamMedium,
		MaxText = 18,
		Parent = frame,
	})
	pop(frame)
	task.delay(3.5, function()
		frame:Destroy()
	end)
end

-- Texte "+X" qui s'envole au-dessus du bouton
local function floatingText(text: string)
	local rng = Random.new()
	local floating = label({
		Text = text,
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, rng:NextInteger(-90, 90), 1, -110),
		Size = UDim2.new(0, 140, 0, 36),
		TextColor3 = COLORS.Gold,
		Font = Enum.Font.GothamBlack,
		MaxText = 28,
		Parent = gui,
	})
	create("UIStroke", { Color = Color3.new(0, 0, 0), Thickness = 2, Parent = floating })
	TweenService:Create(floating, TweenInfo.new(0.8), {
		Position = floating.Position - UDim2.fromOffset(0, 80),
		TextTransparency = 1,
	}):Play()
	task.delay(0.8, function()
		floating:Destroy()
	end)
end

-- Panneaux ---------------------------------------------------------------------

local panels = {}

local function makePanel(title: string, accent: Color3)
	local panel = create("Frame", {
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromScale(0.9, 0.7),
		BackgroundColor3 = COLORS.Panel,
		Visible = false,
		ZIndex = 5,
		Parent = gui,
	}, {
		corner(18),
		stroke(accent, 3),
		create("UISizeConstraint", { MaxSize = Vector2.new(520, 440) }),
	})
	label({
		Text = title,
		Size = UDim2.new(1, -70, 0, 44),
		Position = UDim2.new(0, 16, 0, 8),
		TextXAlignment = Enum.TextXAlignment.Left,
		Font = Enum.Font.GothamBlack,
		MaxText = 30,
		ZIndex = 6,
		Parent = panel,
	})
	local close = button({
		Text = "X",
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -10, 0, 10),
		Size = UDim2.new(0, 40, 0, 40),
		BackgroundColor3 = COLORS.Red,
		ZIndex = 6,
		Parent = panel,
	})
	close.Activated:Connect(function()
		panel.Visible = false
	end)
	local list = create("ScrollingFrame", {
		Position = UDim2.new(0, 10, 0, 60),
		Size = UDim2.new(1, -20, 1, -70),
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		ScrollBarThickness = 6,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		ZIndex = 6,
		Parent = panel,
	}, {
		create("UIListLayout", { Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder }),
		create("UIPadding", { PaddingRight = UDim.new(0, 8) }),
	})
	table.insert(panels, panel)
	return panel, list
end

local function openPanel(panel)
	local wasVisible = panel.Visible
	for _, other in panels do
		other.Visible = false
	end
	panel.Visible = not wasVisible
	if panel.Visible then
		pop(panel)
	end
end

local function makeRow(list, order: number, title: string, accent: Color3)
	local row = create("Frame", {
		Size = UDim2.new(1, 0, 0, 76),
		BackgroundColor3 = COLORS.PanelLight,
		LayoutOrder = order,
		ZIndex = 7,
		Parent = list,
	}, { corner(12) })
	label({
		Text = title,
		Size = UDim2.new(1, -170, 0, 28),
		Position = UDim2.new(0, 12, 0, 8),
		TextXAlignment = Enum.TextXAlignment.Left,
		TextColor3 = accent,
		MaxText = 22,
		ZIndex = 8,
		Parent = row,
	})
	local description = label({
		Text = "",
		Size = UDim2.new(1, -170, 0, 32),
		Position = UDim2.new(0, 12, 0, 38),
		TextXAlignment = Enum.TextXAlignment.Left,
		TextYAlignment = Enum.TextYAlignment.Top,
		TextColor3 = COLORS.Muted,
		Font = Enum.Font.GothamMedium,
		TextWrapped = true,
		MaxText = 15,
		ZIndex = 8,
		Parent = row,
	})
	local action = button({
		Text = "...",
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -10, 0.5, 0),
		Size = UDim2.new(0, 145, 0, 50),
		BackgroundColor3 = accent,
		MaxText = 18,
		ZIndex = 8,
		Parent = row,
	})
	return row, description, action
end

local function sortedKeys(dict)
	local keys = {}
	for key in dict do
		table.insert(keys, key)
	end
	table.sort(keys, function(a, b)
		return dict[a].Order < dict[b].Order
	end)
	return keys
end

-- Panneau Améliorations
local upgradesPanel, upgradesList = makePanel("⬆ Améliorations", COLORS.Blue)
for index, upgradeId in sortedKeys(Config.Upgrades) do
	local upgrade = Config.Upgrades[upgradeId]
	local _, description, action = makeRow(upgradesList, index, upgrade.Name, COLORS.Blue)
	action.Activated:Connect(function()
		Remotes.BuyUpgrade:FireServer(upgradeId)
		pop(action)
	end)
	table.insert(refreshers, function()
		local level = state.Upgrades[upgradeId]
		description.Text = string.format("%s — niveau %d", upgrade.Description, level)
		if Economy.isMaxed(upgradeId, level) then
			action.Text = "MAX"
			action.BackgroundColor3 = COLORS.Disabled
		else
			local cost = Economy.getUpgradeCost(upgradeId, level)
			action.Text = "💰 " .. Economy.formatNumber(cost)
			action.BackgroundColor3 = state.Coins >= cost and COLORS.Green or COLORS.Disabled
		end
	end)
end

-- Panneau Boutique (Robux)
local shopPanel, shopList = makePanel("🛒 Boutique", COLORS.Robux)

local function fetchPrice(id: number, infoType: Enum.InfoType, callback)
	task.spawn(function()
		local ok, info = pcall(function()
			return MarketplaceService:GetProductInfo(id, infoType)
		end)
		if ok and info and info.PriceInRobux then
			callback(info.PriceInRobux)
		end
	end)
end

local order = 0
for _, key in sortedKeys(Config.GamePasses) do
	order += 1
	local pass = Config.GamePasses[key]
	local _, description, action = makeRow(shopList, order, "⭐ " .. pass.Name, COLORS.Purple)
	description.Text = pass.Description
	local price = nil

	local function refresh()
		if pass.Id == 0 then
			action.Text = "Bientôt"
			action.BackgroundColor3 = COLORS.Disabled
		elseif player:GetAttribute(key) then
			action.Text = "Possédé ✔"
			action.BackgroundColor3 = COLORS.Disabled
		else
			action.Text = price and ("R$ " .. price) or "Acheter"
			action.BackgroundColor3 = COLORS.Robux
		end
	end
	refresh()
	player:GetAttributeChangedSignal(key):Connect(refresh)
	if pass.Id ~= 0 then
		fetchPrice(pass.Id, Enum.InfoType.GamePass, function(robux)
			price = robux
			refresh()
		end)
	end

	action.Activated:Connect(function()
		if pass.Id ~= 0 and not player:GetAttribute(key) then
			MarketplaceService:PromptGamePassPurchase(player, pass.Id)
		end
	end)
end

for _, key in sortedKeys(Config.Products) do
	order += 1
	local product = Config.Products[key]
	local _, description, action = makeRow(shopList, order, "💎 " .. product.Name, COLORS.Gold)
	action.TextColor3 = Color3.fromRGB(60, 40, 0)

	if product.Coins then
		table.insert(refreshers, function()
			description.Text = "+" .. Economy.formatNumber(product.Coins * (state.Rebirths + 1)) .. " pièces (augmente avec tes renaissances)"
		end)
	else
		description.Text = "Tous tes gains x3 pendant 15 minutes. Cumulable !"
	end

	if product.Id == 0 then
		action.Text = "Bientôt"
		action.BackgroundColor3 = COLORS.Disabled
	else
		action.Text = "Acheter"
		fetchPrice(product.Id, Enum.InfoType.Product, function(robux)
			action.Text = "R$ " .. robux
		end)
		action.Activated:Connect(function()
			MarketplaceService:PromptProductPurchase(player, product.Id)
		end)
	end
end

-- Panneau Renaissance
local rebirthPanel, rebirthList = makePanel("♻ Renaissance", COLORS.Purple)
do
	local _, description, action = makeRow(rebirthList, 1, "Renaître", COLORS.Purple)
	action.Activated:Connect(function()
		Remotes.Rebirth:FireServer()
		pop(action)
	end)
	table.insert(refreshers, function()
		local cost = Economy.getRebirthCost(state.Rebirths)
		local nextBonus = 1 + (state.Rebirths + 1) * Config.Rebirth.BonusPerRebirth
		description.Text = string.format("Remet pièces et améliorations à zéro. Gains x%.1f pour toujours.", nextBonus)
		action.Text = "💰 " .. Economy.formatNumber(cost)
		action.BackgroundColor3 = state.Coins >= cost and COLORS.Green or COLORS.Disabled
	end)
end

-- Menu de gauche
local menu = create("Frame", {
	AnchorPoint = Vector2.new(0, 0.5),
	Position = UDim2.new(0, 10, 0.5, 0),
	Size = UDim2.new(0, 170, 0, 190),
	BackgroundTransparency = 1,
	Parent = gui,
}, {
	create("UIListLayout", { Padding = UDim.new(0, 10), SortOrder = Enum.SortOrder.LayoutOrder }),
})

for index, info in {
	{ "⬆ Améliorations", COLORS.Blue, upgradesPanel },
	{ "🛒 Boutique", COLORS.Robux, shopPanel },
	{ "♻ Renaissance", COLORS.Purple, rebirthPanel },
} do
	local menuButton = button({
		Text = info[1],
		Size = UDim2.new(1, 0, 0, 56),
		BackgroundColor3 = info[2],
		LayoutOrder = index,
		Parent = menu,
	})
	stroke(Color3.new(0, 0, 0), 2).Parent = menuButton
	menuButton.Activated:Connect(function()
		openPanel(info[3])
	end)
end

-- Réseau ---------------------------------------------------------------------------

local function refreshAll()
	if not state then
		return
	end
	coinsLabel.Text = "💰 " .. Economy.formatNumber(state.Coins)
	clickButton.Text = "CLIQUE !  +" .. Economy.formatNumber(Economy.getClickValue(state) * state.Multiplier)
	for _, refresher in refreshers do
		refresher()
	end
end

Remotes.State.OnClientEvent:Connect(function(newState)
	state = newState
	refreshAll()
end)

Remotes.Notify.OnClientEvent:Connect(toast)

local lastClick = 0
clickButton.Activated:Connect(function()
	local now = os.clock()
	if now - lastClick < Config.ClickCooldown then
		return
	end
	lastClick = now
	Remotes.Click:FireServer()
	pop(clickButton)
	if state then
		floatingText("+" .. Economy.formatNumber(Economy.getClickValue(state) * state.Multiplier))
	end
end)

-- Ligne d'info : multiplicateur + temps de boost restant
task.spawn(function()
	while true do
		if state then
			local parts = { string.format("Gains x%.1f", state.Multiplier) }
			local remaining = state.BoostEndsAt - Workspace:GetServerTimeNow()
			if remaining > 0 then
				table.insert(parts, "⚡ Boost " .. Economy.formatDuration(remaining))
			end
			if player:GetAttribute("AutoClicker") then
				table.insert(parts, "🤖 Auto")
			end
			infoLabel.Text = table.concat(parts, "  •  ")
		end
		task.wait(0.5)
	end
end)
