-- Formules de l'économie, partagées entre serveur et client
-- (le serveur fait foi, le client ne s'en sert que pour l'affichage).

local Config = require(script.Parent:WaitForChild("Config"))

local Economy = {}

function Economy.getUpgradeCost(upgradeId: string, level: number): number
	local upgrade = Config.Upgrades[upgradeId]
	return math.floor(upgrade.BaseCost * upgrade.CostGrowth ^ level)
end

function Economy.isMaxed(upgradeId: string, level: number): boolean
	local maxLevel = Config.Upgrades[upgradeId].MaxLevel
	return maxLevel ~= nil and level >= maxLevel
end

function Economy.getRebirthCost(rebirths: number): number
	return math.floor(Config.Rebirth.BaseCost * (rebirths + 1) ^ 1.5)
end

-- flags = { DoubleCoins = bool, VIP = bool, Boost = bool }
function Economy.getMultiplier(data, flags): number
	local multiplier = 1 + data.Rebirths * Config.Rebirth.BonusPerRebirth
	if flags.DoubleCoins then
		multiplier *= Config.Multipliers.DoubleCoins
	end
	if flags.VIP then
		multiplier *= Config.Multipliers.VIP
	end
	if flags.Boost then
		multiplier *= Config.Multipliers.Boost
	end
	return multiplier
end

function Economy.getClickValue(data): number
	return 1 + data.Upgrades.ClickPower
end

function Economy.getPickupValue(data): number
	return 5 + 3 * data.Upgrades.CoinValue
end

function Economy.getWalkSpeed(data, isVIP: boolean): number
	local speed = Config.BaseWalkSpeed + data.Upgrades.WalkSpeed
	if isVIP then
		speed *= Config.VIPSpeedBonus
	end
	return speed
end

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi", "Sx" }

function Economy.formatNumber(n: number): string
	n = math.floor(n)
	if n < 1000 then
		return tostring(n)
	end
	local value = n
	local index = 1
	while value >= 1000 and index < #SUFFIXES do
		value /= 1000
		index += 1
	end
	local text = string.format("%.1f", value):gsub("%.0$", "")
	return text .. SUFFIXES[index]
end

function Economy.formatDuration(seconds: number): string
	seconds = math.max(0, math.floor(seconds))
	return string.format("%d:%02d", seconds // 60, seconds % 60)
end

return Economy
