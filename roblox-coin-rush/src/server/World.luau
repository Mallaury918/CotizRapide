-- Construit la carte et fait apparaître les pièces à ramasser.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))

local World = {}

local function part(props)
	local p = Instance.new("Part")
	p.Anchored = true
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	if props.Shape then
		p.Shape = props.Shape -- avant Size, sinon la taille est recalculée
	end
	for key, value in props do
		if key ~= "Parent" and key ~= "Shape" then
			p[key] = value
		end
	end
	p.Parent = props.Parent
	return p
end

local function addTree(parent, position: Vector3, rng: Random)
	local height = rng:NextNumber(8, 14)
	part({
		Name = "Trunk",
		Size = Vector3.new(2, height, 2),
		Position = position + Vector3.new(0, height / 2, 0),
		Color = Color3.fromRGB(110, 72, 40),
		Material = Enum.Material.Wood,
		Parent = parent,
	})
	local leaves = part({
		Name = "Leaves",
		Shape = Enum.PartType.Ball,
		Size = Vector3.one * rng:NextNumber(8, 12),
		Position = position + Vector3.new(0, height + 2, 0),
		Color = Color3.fromRGB(58, 150, 70),
		Material = Enum.Material.Grass,
		Parent = parent,
	})
	leaves.CanCollide = false
end

function World.buildMap()
	if Workspace:FindFirstChild("CoinRushMap") then
		return
	end
	local size = Config.World.AreaSize
	local map = Instance.new("Model")
	map.Name = "CoinRushMap"

	part({
		Name = "Ground",
		Size = Vector3.new(size + 60, 4, size + 60),
		Position = Vector3.new(0, -1.95, 0), -- dessus à y = 0.05 (évite de clignoter avec la Baseplate par défaut)
		Color = Color3.fromRGB(92, 184, 92),
		Material = Enum.Material.Grass,
		Parent = map,
	})

	-- Murs invisibles autour de la zone
	local half = size / 2 + 30
	for _, info in {
		{ Vector3.new(half, 25, 0), Vector3.new(2, 50, half * 2) },
		{ Vector3.new(-half, 25, 0), Vector3.new(2, 50, half * 2) },
		{ Vector3.new(0, 25, half), Vector3.new(half * 2, 50, 2) },
		{ Vector3.new(0, 25, -half), Vector3.new(half * 2, 50, 2) },
	} do
		part({ Name = "Wall", Position = info[1], Size = info[2], Transparency = 1, Parent = map })
	end

	local spawn = Instance.new("SpawnLocation")
	spawn.Anchored = true
	spawn.Neutral = true
	spawn.Size = Vector3.new(14, 1, 14)
	spawn.Position = Vector3.new(0, 0.55, 0)
	spawn.Color = Color3.fromRGB(255, 200, 40)
	spawn.Material = Enum.Material.SmoothPlastic
	spawn.Duration = 0
	spawn.Parent = map

	local rng = Random.new(42)
	for _ = 1, 30 do
		local x = rng:NextNumber(-size / 2, size / 2)
		local z = rng:NextNumber(-size / 2, size / 2)
		if math.abs(x) > 20 or math.abs(z) > 20 then
			addTree(map, Vector3.new(x, 0, z), rng)
		end
	end

	map.Parent = Workspace
end

-- onCollect(player, multiplier) est appelé quand un joueur ramasse une pièce.
function World.startCoinSpawner(onCollect)
	local folder = Instance.new("Folder")
	folder.Name = "Coins"
	folder.Parent = Workspace

	local rng = Random.new()
	local half = Config.World.AreaSize / 2

	local function spawnCoin()
		local isGolden = rng:NextNumber() < Config.World.GoldenChance
		local coin = part({
			Name = isGolden and "GoldenCoin" or "Coin",
			Shape = Enum.PartType.Cylinder,
			Size = isGolden and Vector3.new(0.6, 5, 5) or Vector3.new(0.4, 3, 3),
			Color = isGolden and Color3.fromRGB(255, 120, 20) or Color3.fromRGB(255, 215, 0),
			Material = Enum.Material.Neon,
			CanCollide = false,
			CanQuery = false,
			CFrame = CFrame.new(rng:NextNumber(-half, half), isGolden and 3.5 or 2.5, rng:NextNumber(-half, half))
				* CFrame.Angles(0, rng:NextNumber(0, math.pi * 2), 0),
		})

		local connection
		connection = coin.Touched:Connect(function(hit)
			if coin:GetAttribute("Taken") then
				return
			end
			local character = hit:FindFirstAncestorOfClass("Model")
			local player = character and Players:GetPlayerFromCharacter(character)
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")
			if not player or not humanoid or humanoid.Health <= 0 then
				return
			end
			coin:SetAttribute("Taken", true)
			connection:Disconnect()
			coin:Destroy()
			onCollect(player, isGolden and Config.World.GoldenMultiplier or 1)
			task.delay(Config.World.RespawnDelay, spawnCoin)
		end)

		coin.Parent = folder
	end

	for _ = 1, Config.World.MaxCoins do
		spawnCoin()
	end
end

return World
