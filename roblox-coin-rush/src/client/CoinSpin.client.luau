-- Fait tourner et flotter les pièces (uniquement visuel, côté client).

local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local coinsFolder = Workspace:WaitForChild("Coins")
local baseCFrames = {} -- [Part] = CFrame d'origine

coinsFolder.ChildAdded:Connect(function(coin)
	if coin:IsA("BasePart") then
		baseCFrames[coin] = coin.CFrame
	end
end)
coinsFolder.ChildRemoved:Connect(function(coin)
	baseCFrames[coin] = nil
end)
for _, coin in coinsFolder:GetChildren() do
	if coin:IsA("BasePart") then
		baseCFrames[coin] = coin.CFrame
	end
end

RunService.RenderStepped:Connect(function()
	local t = os.clock()
	for coin, base in baseCFrames do
		coin.CFrame = base * CFrame.new(0, math.sin(t * 2 + base.X) * 0.4, 0) * CFrame.Angles(0, t * 2, 0)
	end
end)
