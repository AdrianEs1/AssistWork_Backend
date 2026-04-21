SUPPORTED_INTEGRATIONS = {
    # 🔵 GOOGLE
    "google:gmail": {
        "provider": "google",
        "service": "gmail",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send"
        ]
    },

    "google:sheets":{
        "provider": "google",
        "service": "sheets",
        "scopes": [
            "https://www.googleapis.com/auth/spreadsheets"
        ]


    },
    
    # 🔵 MICROSOFT
    "microsoft:teams": {
    "provider": "microsoft",
    "service": "teams",
    "scopes": [
        "openid",
        "profile",
        "email",
        "offline_access",
        "https://graph.microsoft.com/User.Read",
        "https://graph.microsoft.com/Chat.Read",
        "https://graph.microsoft.com/Chat.ReadWrite",
        "https://graph.microsoft.com/ChatMessage.Send",
        "https://graph.microsoft.com/ChannelMessage.Send",
        "https://graph.microsoft.com/Team.ReadBasic.All",
        "https://graph.microsoft.com/Channel.ReadBasic.All",
    ]
},

# 🔵 HUBSPOT
"hubspot:crm": {
    "provider": "hubspot",
    "service": "crm",
    "scopes": [
        "crm.objects.contacts.read",
        "crm.objects.contacts.write",
        "crm.objects.deals.read",
        "crm.objects.deals.write",
        "crm.objects.companies.read",
        "crm.objects.companies.write",
    ]
},
}

