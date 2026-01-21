import logging
from config import Config
from database import Database
from api_client import ClashRoyaleAPI

logger = logging.getLogger(__name__)

class NicknameManager:
    def __init__(self, api: ClashRoyaleAPI, db: Database):
        self.api = api
        self.db = db
    
    def format_nickname(self, player_name, clan_role, player_tag=None):
        """Форматирование никнейма по шаблону"""
        emoji = Config.ROLE_EMOJIS.get(clan_role.lower(), Config.ROLE_EMOJIS['member'])
        
        nickname = Config.NICKNAME_FORMAT.format(
            emoji=emoji,
            name=player_name,
            tag=player_tag or '',
            role=clan_role
        )
        
        # Обрезаем если слишком длинный (Telegram limit: 64 chars)
        if len(nickname) > 64:
            nickname = nickname[:61] + "..."
        
        return nickname.strip()
    
    def update_user_nickname(self, bot, chat_id, telegram_id, cr_tag):
        """Автоматическое обновление никнейма для пользователя"""
        try:
            # 1. Получаем данные игрока из API
            player_data = self.api.get_player_info(cr_tag)
            if not player_data:
                logger.error(f"Player data not found for tag: {cr_tag}")
                return False, "Данные игрока не найдены"
            
            player_name = player_data.get('name', '')
            if not player_name:
                return False, "Имя игрока не найдено"
            
            # 2. Получаем текущую роль в клане
            current_role = self.api.get_player_role_in_clan(cr_tag, Config.CLAN_TAG)
            if not current_role:
                current_role = 'member'  # Роль по умолчанию
            
            # 3. Форматируем никнейм
            nickname = self.format_nickname(player_name, current_role, cr_tag)
            
            # 4. Обновляем в Telegram
            bot.set_chat_administrator_custom_title(
                chat_id=chat_id,
                user_id=telegram_id,
                custom_title=nickname
            )
            
            # 5. Сохраняем в БД
            self.db.update_user_nickname(telegram_id, player_name, current_role)
            
            logger.info(f"Nickname updated for {telegram_id}: {player_name} ({current_role})")
            return True, nickname
            
        except Exception as e:
            logger.error(f"Failed to update nickname for {telegram_id}: {e}")
            return False, str(e)
    
    def update_all_nicknames(self, bot, chat_id):
        """Обновление всех никнеймов в чате"""
        try:
            users = self.db.get_all_users()
            updated = 0
            failed = 0
            results = []
            
            for user in users:
                if user['cr_tag']:
                    success, result = self.update_user_nickname(
                        bot, chat_id, user['telegram_id'], user['cr_tag']
                    )
                    
                    if success:
                        updated += 1
                        results.append(f"✅ {user.get('username', 'Unknown')}: обновлен")
                    else:
                        failed += 1
                        results.append(f"❌ {user.get('username', 'Unknown')}: {result}")
            
            return updated, failed, results
            
        except Exception as e:
            logger.error(f"Failed to update all nicknames: {e}")
            return 0, 0, [f"Ошибка: {str(e)}"]
    
    def get_clan_role(self, player_tag):
        """Получение роли игрока в клане"""
        return self.api.get_player_role_in_clan(player_tag, Config.CLAN_TAG)
    
    def sync_player_data(self, telegram_id, cr_tag):
        """Синхронизация данных игрока (имя и роль) с API"""
        try:
            player_data = self.api.get_player_info(cr_tag)
            if not player_data:
                return False, "Данные игрока не найдены"
            
            player_name = player_data.get('name', '')
            if not player_name:
                return False, "Имя игрока не найдено"
            
            # Получаем роль
            current_role = self.api.get_player_role_in_clan(cr_tag, Config.CLAN_TAG)
            if not current_role:
                current_role = 'member'
            
            # Обновляем в БД
            self.db.update_user_nickname(telegram_id, player_name, current_role)
            
            return True, {
                'name': player_name,
                'role': current_role,
                'trophies': player_data.get('trophies', 0),
                'level': player_data.get('expLevel', 1)
            }
            
        except Exception as e:
            logger.error(f"Failed to sync player data for {telegram_id}: {e}")
            return False, str(e)