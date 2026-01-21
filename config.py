import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Bot
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    # Clash Royale API
    CR_API_TOKEN = os.getenv("CR_API_TOKEN")
    USE_PROXY = os.getenv("USE_PROXY", "true").lower() == "true"
    API_BASE_URL = "https://proxy.royaleapi.dev/v1" if USE_PROXY else "https://api.clashroyale.com/v1"
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    # Admin & Clan
    ADMIN_TAG = os.getenv("ADMIN_TAG", "#YOUR_TAG_HERE")
    CLAN_TAG = os.getenv("CLAN_TAG", "#YOUR_CLAN_TAG")
    
    # Group Chat
    GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "")
    
    # War Settings
    WAR_REMINDER_ENABLED = os.getenv("WAR_REMINDER_ENABLED", "true").lower() == "true"
    WAR_REMINDER_TIME = os.getenv("WAR_REMINDER_TIME", "18:00")
    WAR_ATTACK_REMINDER = os.getenv("WAR_ATTACK_REMINDER", "true").lower() == "true"
    
    # Auto-kick Settings
    AUTO_KICK_ENABLED = os.getenv("AUTO_KICK_ENABLED", "false").lower() == "true"
    KICK_AFTER_DAYS = int(os.getenv("KICK_AFTER_DAYS", "14"))
    WARNING_BEFORE_KICK = int(os.getenv("WARNING_BEFORE_KICK", "3"))
    
    # Nickname Settings
    AUTO_NICKNAME_ENABLED = os.getenv("AUTO_NICKNAME_ENABLED", "true").lower() == "true"
    NICKNAME_FORMAT = os.getenv("NICKNAME_FORMAT", "{emoji} {name}")
    NICKNAME_UPDATE_INTERVAL = int(os.getenv("NICKNAME_UPDATE_INTERVAL", "3600"))
    
    # Webhook (for Railway)
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
    PORT = int(os.getenv("PORT", 8443))
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    # Emojis
    EMOJI = {
        'crown': '👑',
        'trophy': '🏆',
        'sword': '⚔️',
        'shield': '🛡️',
        'person': '👤',
        'clan': '🏰',
        'calendar': '📅',
        'warning': '⚠️',
        'success': '✅',
        'error': '❌',
        'info': 'ℹ️',
        'cards': '🃏',
        'chest': '🎁',
        'admin': '⚙️',
        'bell': '🔔',
        'users': '👥',
        'clock': '⏰',
        'fire': '🔥',
        'boot': '👢',
        'megaphone': '📢',
        'target': '🎯'
    }
    
    ROLE_EMOJIS = {
        'leader': '👑',
        'coLeader': '⭐',
        'admin': '🔧',
        'elder': '🛡️',
        'member': '🎮'
    }
    
# Admin Promotion Settings
AUTO_PROMOTE_TO_ADMIN = os.getenv("AUTO_PROMOTE_TO_ADMIN", "true").lower() == "true"
MIN_ADMIN_RIGHTS = {
    'can_delete_messages': False,
    'can_restrict_members': False,
    'can_promote_members': False,
    'can_change_info': False,
    'can_invite_users': True,
    'can_pin_messages': False,
    'can_manage_video_chats': False,
    'can_manage_chat': False,
    'can_post_messages': True,
    'can_edit_messages': False,
    'can_manage_topics': False
}