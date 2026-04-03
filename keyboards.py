from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

class Keyboards:
    @staticmethod
    def get_main_menu():
        """Reply keyboard for personal chat"""
        keyboard = [
            ['📊 Моя статистика', '🏰 Информация о клане'],
            ['🎁 Мои сундуки', '⚔️ История боев'],
            ['📝 Регистрация', '❓ Помощь']
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    @staticmethod
    def get_group_menu():
        """Reply keyboard for group chat"""
        keyboard = [
            ['⚔️ Война', '🎯 Атаки'],
            ['👥 Топ игроков', '⚠️ Неактивные'],
            ['🏰 Информация', '📜 Правила'],
            ['🏞️ Речная гонка', '📜 История войн'],
            ['🏆 Турниры', '🏅 Рейтинги'],
            ['❓ Помощь', '📝 Регистрация']
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    @staticmethod
    def get_war_keyboard():
        """Inline keyboard for war info"""
        keyboard = [
            [
                InlineKeyboardButton("🎯 Статус атак", callback_data="war_attacks"),
                InlineKeyboardButton("📊 Детали", callback_data="war_details")
            ],
            [
                InlineKeyboardButton("👥 Участники", callback_data="war_participants"),
                InlineKeyboardButton("🏆 Результат", callback_data="war_result")
            ],
            [
                InlineKeyboardButton("🔄 Обновить", callback_data="refresh_war"),
                InlineKeyboardButton("🔔 Напомнить", callback_data="remind_war")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_clan_keyboard():
        """Inline keyboard for clan info"""
        keyboard = [
            [
                InlineKeyboardButton("👥 Участники", callback_data="show_members"),
                InlineKeyboardButton("🏆 Топ игроков", callback_data="top_players")
            ],
            [
                InlineKeyboardButton("⚔️ Война", callback_data="war_info"),
                InlineKeyboardButton("📊 Донаты", callback_data="show_donations")
            ],
            [
                InlineKeyboardButton("🔄 Обновить", callback_data="refresh_clan"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_stats_keyboard():
        """Inline keyboard for player stats"""
        keyboard = [
            [
                InlineKeyboardButton("🎁 Мои сундуки", callback_data="my_chests"),
                InlineKeyboardButton("⚔️ Мои бои", callback_data="my_battles")
            ],
            [
                InlineKeyboardButton("🏰 Мой клан", callback_data="my_clan"),
                InlineKeyboardButton("🔄 Обновить", callback_data="refresh_stats")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_admin_keyboard():
        """Inline keyboard for admin panel"""
        keyboard = [
            [
                InlineKeyboardButton("👢 Исключить", callback_data="admin_kick"),
                InlineKeyboardButton("⚠️ Предупредить", callback_data="admin_warn")
            ],
            [
                InlineKeyboardButton("🔄 Обновить никнеймы", callback_data="admin_update_nicks"),
                InlineKeyboardButton("🔄 Синхр. роли", callback_data="admin_sync_roles")
            ],
            [
                InlineKeyboardButton("🔔 Напомнить о войне", callback_data="admin_remind"),
                InlineKeyboardButton("🏞️ Проверить речную гонку", callback_data="admin_river_check")
            ],
            [
                InlineKeyboardButton("⚙️ Настройки чата", callback_data="admin_settings"),
                InlineKeyboardButton("📈 Статистика", callback_data="admin_stats")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_confirmation_keyboard(action, target_id=None):
        """Confirmation keyboard for actions"""
        if target_id:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Да", callback_data=f"confirm_{action}_{target_id}"),
                    InlineKeyboardButton("❌ Нет", callback_data=f"cancel_{action}")
                ]
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Да", callback_data=f"confirm_{action}"),
                    InlineKeyboardButton("❌ Нет", callback_data=f"cancel_{action}")
                ]
            ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_register_keyboard(bot_username):
        """Keyboard for registration"""
        keyboard = [
            [
                InlineKeyboardButton("📝 Регистрация", url=f"https://t.me/{bot_username}?start=register"),
                InlineKeyboardButton("❓ Помощь", callback_data="help_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)