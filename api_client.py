import requests
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

class ClashRoyaleAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = Config.API_BASE_URL  # ← Используем из конфига!
        
        logger.info(f"Использую API URL: {self.base_url}")
        
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Accept': 'application/json'
        }
        
        # Проверяем подключение при старте
        self._test_connection()
    
    def _test_connection(self):
        """Тестирование подключения к API"""
        try:
            logger.info("🔍 Проверяю подключение к API...")
            response = requests.get(
                f"{self.base_url}/cards",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ API подключение успешно! Карт в игре: {len(data.get('items', []))}")
                return True
            else:
                logger.error(f"❌ Ошибка API: {response.status_code} - {response.text[:100]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к API: {e}")
            return False
    
    def _encode_tag(self, tag):
        """Кодирование тега для URL"""
        if not tag.startswith('#'):
            tag = '#' + tag
        return requests.utils.quote(tag)
    
    # ВСЕ ОСТАЛЬНЫЕ МЕТОДЫ ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ!
    # Просто они будут использовать self.base_url который теперь ведет на прокси
    
    def get_player_info(self, player_tag):
        encoded_tag = self._encode_tag(player_tag)
        url = f"{self.base_url}/players/{encoded_tag}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"API error for player {player_tag}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Request error for player {player_tag}: {e}")
            return None
    
    def get_clan_info(self, clan_tag):
        encoded_tag = self._encode_tag(clan_tag)
        url = f"{self.base_url}/clans/{encoded_tag}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for clan {clan_tag}: {e}")
            return None
    
    def get_clan_members(self, clan_tag):
        encoded_tag = self._encode_tag(clan_tag)
        url = f"{self.base_url}/clans/{encoded_tag}/members"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('items', [])
            return None
        except Exception as e:
            logger.error(f"Request error for clan members {clan_tag}: {e}")
            return None
    
    def get_current_war(self, clan_tag):
        encoded_tag = self._encode_tag(clan_tag)
        url = f"{self.base_url}/clans/{encoded_tag}/currentwar"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for current war {clan_tag}: {e}")
            return None
    
    def get_player_chests(self, player_tag):
        encoded_tag = self._encode_tag(player_tag)
        url = f"{self.base_url}/players/{encoded_tag}/upcomingchests"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for chests {player_tag}: {e}")
            return None
    
    def get_battle_log(self, player_tag, limit=10):
        encoded_tag = self._encode_tag(player_tag)
        url = f"{self.base_url}/players/{encoded_tag}/battlelog"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                battles = response.json()
                return battles[:limit] if limit else battles
            return None
        except Exception as e:
            logger.error(f"Request error for battle log {player_tag}: {e}")
            return None
    
    def get_player_role_in_clan(self, player_tag, clan_tag):
        members = self.get_clan_members(clan_tag)
        if not members:
            return None
        
        for member in members:
            if member.get('tag') == player_tag:
                return member.get('role', 'member')
        
        return None
    
    def format_player_stats(self, player_data):
        if not player_data:
            return "❌ Не удалось получить данные игрока"
        
        emoji = Config.EMOJI
        text = f"{emoji['person']} *{player_data.get('name')}*\n"
        text += f"{emoji['crown']} Уровень: {player_data.get('expLevel')}\n"
        text += f"{emoji['trophy']} Трофеи: {player_data.get('trophies'):,}\n"
        text += f"{emoji['trophy']} Лучшие трофеи: {player_data.get('bestTrophies'):,}\n\n"
        
        wins = player_data.get('wins', 0)
        losses = player_data.get('losses', 0)
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        
        text += f"{emoji['sword']} *Статистика боев:*\n"
        text += f"• Побед: {wins:,}\n"
        text += f"• Поражений: {losses:,}\n"
        text += f"• Процент побед: {win_rate:.1f}%\n"
        
        if 'threeCrownWins' in player_data:
            text += f"• Трехкоронных побед: {player_data.get('threeCrownWins'):,}\n"
        
        if 'currentDeck' in player_data:
            text += f"\n{emoji['cards']} *Текущая колода:*\n"
            for card in player_data['currentDeck'][:4]:
                text += f"• {card.get('name')} (Ур. {card.get('level')})\n"
        
        if 'clan' in player_data and player_data['clan']:
            clan = player_data['clan']
            text += f"\n{emoji['clan']} *Клан:* {clan.get('name')}\n"
            text += f"• Роль: {clan.get('role')}\n"
        
        return text