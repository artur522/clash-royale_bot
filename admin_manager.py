import logging
from telegram import Bot
from config import Config

logger = logging.getLogger(__name__)

class AdminManager:
    def __init__(self, bot: Bot = None):
        self.bot = bot
    
    def set_bot(self, bot: Bot):
        self.bot = bot
    
    def promote_user(self, chat_id: int, user_id: int):
        """Назначение пользователя администратором с минимальными правами"""
        try:
            # Проверяем, является ли пользователь уже администратором
            chat_member = self.bot.get_chat_member(chat_id, user_id)
            
            if chat_member.status not in ['administrator', 'creator']:
                # Назначаем администратором с минимальными правами
                success = self.bot.promote_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    **Config.MIN_ADMIN_RIGHTS
                )
                
                if success:
                    logger.info(f"User {user_id} promoted to admin in chat {chat_id}")
                    return True, "Назначены права администратора"
                else:
                    return False, "Не удалось назначить права администратора"
            else:
                return True, "Пользователь уже является администратором"
                
        except Exception as e:
            logger.error(f"Error promoting user {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def set_custom_title(self, chat_id: int, user_id: int, title: str):
        """Установка кастомного заголовка (роли)"""
        try:
            if len(title) > 16:
                title = title[:13] + "..."
            
            success = self.bot.set_chat_administrator_custom_title(
                chat_id=chat_id,
                user_id=user_id,
                custom_title=title
            )
            
            if success:
                logger.info(f"Custom title '{title}' set for user {user_id}")
                return True, f"Роль установлена: {title}"
            else:
                return False, "Не удалось установить роль"
                
        except Exception as e:
            logger.error(f"Error setting custom title for user {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def promote_and_set_title(self, chat_id: int, user_id: int, title: str):
        """Назначить администратором и установить роль (все в одном)"""
        if Config.AUTO_PROMOTE_TO_ADMIN:
            # 1. Назначаем администратором
            promote_success, promote_msg = self.promote_user(chat_id, user_id)
            
            if promote_success:
                # 2. Устанавливаем роль
                title_success, title_msg = self.set_custom_title(chat_id, user_id, title)
                
                if title_success:
                    return True, f"{promote_msg}\n{title_msg}"
                else:
                    return False, title_msg
            else:
                return False, promote_msg
        else:
            # Если автоназначение отключено, только устанавливаем роль
            return self.set_custom_title(chat_id, user_id, title)