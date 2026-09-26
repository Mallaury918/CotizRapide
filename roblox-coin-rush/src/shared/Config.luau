-- Configuration centrale du jeu "Coin Rush".
-- ⚠️ Remplace les Id = 0 par les vrais IDs créés sur https://create.roblox.com
-- (Créations > ton expérience > Monétisation > Passes / Produits de développeur).
-- Tant qu'un Id vaut 0, l'objet s'affiche "Bientôt" dans la boutique et ne peut pas être acheté.

local Config = {}

-- Game Passes : achat unique, avantage permanent.
Config.GamePasses = {
	DoubleCoins = {
		Id = 0,
		Name = "x2 Pièces",
		Description = "Double toutes les pièces gagnées. Pour toujours !",
		Order = 1,
	},
	VIP = {
		Id = 0,
		Name = "VIP",
		Description = "+50% de pièces, +30% de vitesse et tag [VIP] doré dans le chat.",
		Order = 2,
	},
	AutoClicker = {
		Id = 0,
		Name = "Auto-Clicker",
		Description = "Clique automatiquement 2 fois par seconde, même AFK.",
		Order = 3,
	},
}

-- Produits de développeur : achetables à l'infini (consommables).
-- Les packs de pièces sont multipliés par (Renaissances + 1) pour rester utiles.
Config.Products = {
	SmallCoins = {
		Id = 0,
		Name = "Petit sac de pièces",
		Coins = 1000,
		Order = 1,
	},
	BigCoins = {
		Id = 0,
		Name = "Coffre de pièces",
		Coins = 15000,
		Order = 2,
	},
	HugeCoins = {
		Id = 0,
		Name = "Trésor légendaire",
		Coins = 100000,
		Order = 3,
	},
	Boost = {
		Id = 0,
		Name = "Boost x3 (15 min)",
		BoostSeconds = 15 * 60,
		Order = 4,
	},
}

-- Améliorations achetables avec les pièces du jeu.
Config.Upgrades = {
	ClickPower = {
		Name = "Puissance de clic",
		Description = "+1 pièce par clic",
		BaseCost = 15,
		CostGrowth = 1.15,
		Order = 1,
	},
	CoinValue = {
		Name = "Pièces dorées",
		Description = "+3 par pièce ramassée au sol",
		BaseCost = 50,
		CostGrowth = 1.2,
		Order = 2,
	},
	WalkSpeed = {
		Name = "Baskets rapides",
		Description = "+1 vitesse de marche",
		BaseCost = 100,
		CostGrowth = 1.35,
		MaxLevel = 20,
		Order = 3,
	},
}

Config.Rebirth = {
	BaseCost = 25000, -- coût = BaseCost * (renaissances + 1) ^ 1.5
	BonusPerRebirth = 0.5, -- +50% de gains par renaissance
}

Config.Multipliers = {
	DoubleCoins = 2,
	VIP = 1.5,
	Boost = 3,
}

Config.BaseWalkSpeed = 16
Config.VIPSpeedBonus = 1.3
Config.ClickCooldown = 0.08 -- anti-triche : ~12 clics/s maximum
Config.AutoClickInterval = 0.5

Config.World = {
	AreaSize = 220, -- taille de la zone de jeu (studs)
	MaxCoins = 45, -- pièces présentes en même temps
	RespawnDelay = 3,
	GoldenChance = 0.06, -- chance qu'une pièce soit dorée
	GoldenMultiplier = 10,
}

return Config
