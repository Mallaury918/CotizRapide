-- Tag [VIP] doré devant le nom des joueurs VIP dans le chat (TextChatService).

local Players = game:GetService("Players")
local TextChatService = game:GetService("TextChatService")

TextChatService.OnIncomingMessage = function(message: TextChatMessage)
	local properties = Instance.new("TextChatMessageProperties")
	local source = message.TextSource
	local sender = source and Players:GetPlayerByUserId(source.UserId)
	if sender and sender:GetAttribute("VIP") then
		properties.PrefixText = '<font color="#FFD700">[VIP]</font> ' .. message.PrefixText
	end
	return properties
end
