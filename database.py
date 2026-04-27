import os
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from contextlib import contextmanager
from config import Config
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.database_url = Config.DATABASE_URL
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = psycopg2.connect(self.database_url, sslmode='require')
            yield conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    @contextmanager
    def get_cursor(self, conn=None):
        if conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield cursor
                conn.commit()
            finally:
                cursor.close()
        else:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    yield cursor
                    conn.commit()
                finally:
                    cursor.close()
    
    def init_db(self):
        try:
            with self.get_cursor() as cursor:
                # Users table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        telegram_id BIGINT PRIMARY KEY,
                        cr_tag VARCHAR(20) NOT NULL,
                        username VARCHAR(100),
                        is_admin BOOLEAN DEFAULT FALSE,
                        clan_role VARCHAR(20) DEFAULT 'member',
                        notification_enabled BOOLEAN DEFAULT TRUE,
                        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        nickname_updated TIMESTAMP
                    )
                ''')
                
                # Player activity
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS player_activity (
                        id SERIAL PRIMARY KEY,
                        cr_tag VARCHAR(20) NOT NULL,
                        trophies INTEGER,
                        donations INTEGER,
                        last_battle TIMESTAMP,
                        check_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Chat settings
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS chat_settings (
                        chat_id BIGINT PRIMARY KEY,
                        chat_title VARCHAR(255),
                        is_group_chat BOOLEAN DEFAULT TRUE,
                        welcome_message TEXT,
                        rules_message TEXT,
                        nickname_format VARCHAR(100) DEFAULT '{emoji} {name}',
                        auto_kick_enabled BOOLEAN DEFAULT FALSE,
                        war_reminders_enabled BOOLEAN DEFAULT TRUE,
                        last_war_check TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Warnings
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS warnings (
                        id SERIAL PRIMARY KEY,
                        telegram_id BIGINT,
                        cr_tag VARCHAR(20),
                        warning_type VARCHAR(50),
                        message TEXT,
                        warning_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_resolved BOOLEAN DEFAULT FALSE,
                        resolved_date TIMESTAMP
                    )
                ''')
                
                # Kicked players
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS kicked_players (
                        id SERIAL PRIMARY KEY,
                        player_tag VARCHAR(20),
                        player_name VARCHAR(100),
                        kick_reason VARCHAR(255),
                        kicked_by VARCHAR(100),
                        kick_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        days_inactive INTEGER
                    )
                ''')
                
                # Votes
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS votes (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT,
                        vote_type VARCHAR(50),
                        target_tag VARCHAR(20),
                        target_name VARCHAR(100),
                        votes_for INTEGER DEFAULT 0,
                        votes_against INTEGER DEFAULT 0,
                        voters JSONB,
                        status VARCHAR(20) DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP
                    )
                ''')
                
                # Raffle numbers
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS raffle_numbers (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        number INTEGER NOT NULL,
                        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chat_id, user_id),
                        UNIQUE(chat_id, number)
                    )
                ''')
                
                # Indexes
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_cr_tag ON users(cr_tag)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_cr_tag ON player_activity(cr_tag)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_raffle_chat ON raffle_numbers(chat_id)')
                
                # Initialize admin user
                self._init_admin_user(cursor)
                
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
    
    def _init_admin_user(self, cursor):
        admin_tag = Config.ADMIN_TAG
        if admin_tag and admin_tag != "#YOUR_TAG_HERE":
            cursor.execute('''
                INSERT INTO users (telegram_id, cr_tag, username, is_admin)
                VALUES (0, %s, 'admin', TRUE)
                ON CONFLICT (telegram_id) DO NOTHING
            ''', (admin_tag,))
    
    def register_user(self, telegram_id, cr_tag, username=None):
        try:
            with self.get_cursor() as cursor:
                is_admin = (cr_tag == Config.ADMIN_TAG)
                cursor.execute('''
                    INSERT INTO users (telegram_id, cr_tag, username, is_admin, last_activity)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET cr_tag = EXCLUDED.cr_tag,
                        username = EXCLUDED.username,
                        is_admin = EXCLUDED.is_admin,
                        last_activity = CURRENT_TIMESTAMP
                    RETURNING *
                ''', (telegram_id, cr_tag, username, is_admin))
                
                user = cursor.fetchone()
                return dict(user) if user else None
        except Exception as e:
            logger.error(f"Register user error: {e}")
            return None
    
    def get_user_by_telegram_id(self, telegram_id):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('SELECT * FROM users WHERE telegram_id = %s', (telegram_id,))
                user = cursor.fetchone()
                return dict(user) if user else None
        except Exception as e:
            logger.error(f"Get user error: {e}")
            return None
    
    def get_user_by_cr_tag(self, cr_tag):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('SELECT * FROM users WHERE cr_tag = %s', (cr_tag,))
                user = cursor.fetchone()
                return dict(user) if user else None
        except Exception as e:
            logger.error(f"Get user by tag error: {e}")
            return None
    
    def is_admin(self, telegram_id):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('SELECT is_admin FROM users WHERE telegram_id = %s', (telegram_id,))
                result = cursor.fetchone()
                return result['is_admin'] if result else False
        except Exception as e:
            logger.error(f"Check admin error: {e}")
            return False
    
    def update_user_activity(self, telegram_id):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('''
                    UPDATE users 
                    SET last_activity = CURRENT_TIMESTAMP 
                    WHERE telegram_id = %s
                ''', (telegram_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Update activity error: {e}")
            return False
    
    def update_user_nickname(self, telegram_id, cr_name, clan_role):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('''
                    UPDATE users 
                    SET username = %s, clan_role = %s, nickname_updated = CURRENT_TIMESTAMP
                    WHERE telegram_id = %s
                ''', (cr_name, clan_role, telegram_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Update nickname error: {e}")
            return False
    
    def get_all_users(self):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('SELECT * FROM users WHERE telegram_id > 0 ORDER BY last_activity DESC')
                users = [dict(row) for row in cursor.fetchall()]
                return users
        except Exception as e:
            logger.error(f"Get all users error: {e}")
            return []
    
    def register_chat(self, chat_id, chat_title, is_group=True):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('''
                    INSERT INTO chat_settings (chat_id, chat_title, is_group_chat)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (chat_id) DO UPDATE
                    SET chat_title = EXCLUDED.chat_title
                ''', (chat_id, chat_title, is_group))
                return True
        except Exception as e:
            logger.error(f"Register chat error: {e}")
            return False
    
    def get_chat_settings(self, chat_id):
        try:
            with self.get_cursor() as cursor:
                cursor.execute('SELECT * FROM chat_settings WHERE chat_id = %s', (chat_id,))
                chat = cursor.fetchone()
                return dict(chat) if chat else None
        except Exception as e:
            logger.error(f"Get chat settings error: {e}")
            return None
    
    def update_chat_setting(self, chat_id, setting_key, setting_value):
        try:
            with self.get_cursor() as cursor:
                cursor.execute(f'''
                    UPDATE chat_settings 
                    SET {setting_key} = %s 
                    WHERE chat_id = %s
                ''', (setting_value, chat_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Update chat setting error: {e}")
            return False
    
    def get_bot_stats(self):
        try:
            with self.get_cursor() as cursor:
                stats = {}
                cursor.execute('SELECT COUNT(*) as count FROM users WHERE telegram_id > 0')
                stats['total_users'] = cursor.fetchone()['count']
                
                cursor.execute('SELECT COUNT(*) as count FROM users WHERE is_admin = TRUE')
                stats['admins'] = cursor.fetchone()['count']
                
                cursor.execute('SELECT COUNT(*) as count FROM warnings WHERE is_resolved = FALSE')
                stats['active_warnings'] = cursor.fetchone()['count']
                
                return stats
        except Exception as e:
            logger.error(f"Get bot stats error: {e}")
            return {}
    
    # Raffle methods
    def assign_raffle_numbers(self, chat_id, user_numbers):
        """Assign raffle numbers to users in a chat. user_numbers is dict {user_id: number}"""
        try:
            with self.get_cursor() as cursor:
                # Clear existing numbers for this chat
                cursor.execute('DELETE FROM raffle_numbers WHERE chat_id = %s', (chat_id,))
                
                # Insert new numbers
                for user_id, number in user_numbers.items():
                    cursor.execute('''
                        INSERT INTO raffle_numbers (chat_id, user_id, number)
                        VALUES (%s, %s, %s)
                    ''', (chat_id, user_id, number))
                
                logger.info(f"Assigned raffle numbers for chat {chat_id}: {len(user_numbers)} participants")
                return True
        except Exception as e:
            logger.error(f"Assign raffle numbers error: {e}")
            return False
    
    def get_raffle_numbers(self, chat_id):
        """Get all raffle numbers for a chat"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute('''
                    SELECT rn.user_id, rn.number, u.username, u.cr_tag
                    FROM raffle_numbers rn
                    LEFT JOIN users u ON rn.user_id = u.telegram_id
                    WHERE rn.chat_id = %s
                    ORDER BY rn.number
                ''', (chat_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Get raffle numbers error: {e}")
            return []
    
    def clear_raffle_numbers(self, chat_id):
        """Clear all raffle numbers for a chat"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute('DELETE FROM raffle_numbers WHERE chat_id = %s', (chat_id,))
                logger.info(f"Cleared raffle numbers for chat {chat_id}")
                return True
        except Exception as e:
            logger.error(f"Clear raffle numbers error: {e}")
            return False
    
    def get_raffle_participants_count(self, chat_id):
        """Get count of participants with raffle numbers"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute('SELECT COUNT(*) as count FROM raffle_numbers WHERE chat_id = %s', (chat_id,))
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Get raffle participants count error: {e}")
            return 0