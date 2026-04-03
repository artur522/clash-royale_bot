import requests
import logging
from datetime import datetime
from config import Config
import redis
import json

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
        
        # Инициализация Redis для кэша
        try:
            self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            self.redis_client.ping()  # Проверяем соединение
            logger.info("✅ Redis подключен для кэширования")
        except:
            self.redis_client = None
            logger.warning("⚠️ Redis недоступен, кэширование отключено")
        
        # Проверяем подключение при старте
        self._test_connection()
    
    def _get_cached(self, key):
        """Получить данные из кэша"""
        if not self.redis_client:
            return None
        try:
            data = self.redis_client.get(key)
            return json.loads(data) if data else None
        except:
            return None
    
    def _set_cached(self, key, data, ttl=300):
        """Сохранить данные в кэш (TTL в секундах)"""
        if not self.redis_client:
            return
        try:
            self.redis_client.setex(key, ttl, json.dumps(data))
        except:
            pass
    
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
        cache_key = f"player:{encoded_tag}"
        
        # Проверяем кэш
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        url = f"{self.base_url}/players/{encoded_tag}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self._set_cached(cache_key, data, 600)  # Кэш на 10 мин
                return data
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
            for card in player_data['currentDeck']:
                text += f"• {card.get('name')} (Ур. {card.get('level')})\n"
        
        if 'clan' in player_data and player_data['clan']:
            clan = player_data['clan']
            text += f"\n{emoji['clan']} *Клан:* {clan.get('name')}\n"
            # Получаем роль игрока в клане
            player_role = self.get_player_role_in_clan(player_data.get('tag'), clan.get('tag'))
            role_names = {
                'member': 'Участник',
                'elder': 'Старейшина',
                'coLeader': 'Зам.лидера',
                'leader': 'Лидер'
            }
            role_display = role_names.get(player_role, player_role or 'Неизвестно')
            text += f"• Роль: {role_display}\n"

            # Получаем информацию о донациях
            try:
                members = self.get_clan_members(clan.get('tag'))
                if members:
                    for member in members:
                        if member.get('tag') == player_data.get('tag'):
                            donations = member.get('donations', 0)
                            donations_received = member.get('donationsReceived', 0)
                            balance = donations - donations_received
                            text += f"\n{emoji['donate']} *Статистика донаций (текущий период):*\n"
                            text += f"• Пожертвовано карт: {donations:,}\n"
                            text += f"• Получено карт: {donations_received:,}\n"
                            text += f"• Баланс: {balance:+,}\n"
                            break
            except:
                pass

        return text
    
    def get_current_river_race(self, clan_tag):
        """Получить текущую речную гонку"""
        encoded_tag = self._encode_tag(clan_tag)
        url = f"{self.base_url}/clans/{encoded_tag}/currentriverrace"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for river race {clan_tag}: {e}")
            return None
    
    def get_war_log(self, clan_tag, limit=10):
        """Получить историю войн клана"""
        encoded_tag = self._encode_tag(clan_tag)
        url = f"{self.base_url}/clans/{encoded_tag}/warlog"
        params = {'limit': limit}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for war log {clan_tag}: {e}")
            return None
    
    def get_river_race_log(self, clan_tag, limit=10):
        """Получить историю речных гонок клана"""
        encoded_tag = self._encode_tag(clan_tag)
        url = f"{self.base_url}/clans/{encoded_tag}/riverracelog"
        params = {'limit': limit}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for river race log {clan_tag}: {e}")
            return None
    
    def search_tournaments(self, name=None, limit=10):
        """Поиск турниров"""
        url = f"{self.base_url}/tournaments"
        params = {'limit': limit}
        if name:
            params['name'] = name
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for tournaments search: {e}")
            return None
    
    def get_tournament_info(self, tournament_tag):
        """Получить информацию о турнире"""
        encoded_tag = self._encode_tag(tournament_tag)
        url = f"{self.base_url}/tournaments/{encoded_tag}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for tournament {tournament_tag}: {e}")
            return None
    
    def get_clan_rankings(self, location_id='global', limit=10):
        """Получить рейтинги кланов"""
        url = f"{self.base_url}/locations/{location_id}/rankings/clans"
        params = {'limit': limit}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for clan rankings {location_id}: {e}")
            return None
    
    def get_player_rankings(self, location_id='global', limit=10):
        """Получить рейтинги игроков"""
        url = f"{self.base_url}/locations/{location_id}/rankings/players"
        params = {'limit': limit}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Request error for player rankings {location_id}: {e}")
            return None

    def format_war_day_alert(self, war_data, clan_members):
        """Красивое сообщение о начале War Day с двумя списками на вылет"""
        if not war_data or war_data.get('state') != 'WAR_DAY':
            return None

        clan = war_data.get('clan', {})
        participants = {p['tag']: p for p in war_data.get('participants', [])}

        # Кто НЕ АТАКОВАЛ (0 боев в КВ)
        not_attacked = []
        for p in war_data.get('participants', []):
            if p.get('battlesPlayed', 0) == 0:
                not_attacked.append(p)

        # Кто НЕ ДОНАТИТ (0 карт за период)
        not_donating = []
        for member in clan_members:
            if member.get('donations', 0) == 0:
                not_donating.append(member)

        return {
            'clan_name': clan.get('name'),
            'clan_score': clan.get('clanScore', 0),
            'participants': len(participants),
            'time_remaining': war_data.get('warEndTime'),
            'not_attacked': not_attacked,
            'not_donating': not_donating,
            'place': clan.get('position', 'N/A')
        }

    def format_donations_full(self, clan_tag):
        """Получить полную статистику донатов всех игроков"""
        members = self.get_clan_members(clan_tag)

        if not members:
            return None

        # Сортируем по пожертвованным картам
        sorted_members = sorted(members, key=lambda x: x.get('donations', 0), reverse=True)

        total_donations = sum(m.get('donations', 0) for m in sorted_members)
        total_received = sum(m.get('donationsReceived', 0) for m in sorted_members)

        return {
            'members': sorted_members,
            'total_donations': total_donations,
            'total_received': total_received,
            'average_donations': total_donations // len(members) if members else 0,
            'average_received': total_received // len(members) if members else 0,
            'count': len(members)
        }

    def format_war_stats(self, war_data):
        """Форматировать статистику войны с рейтингом игроков"""
        if not war_data:
            return None

        participants = war_data.get('participants', [])

        # Сортируем по очкам
        sorted_participants = sorted(participants, key=lambda x: x.get('cardsEarned', 0), reverse=True)

        stats = {
            'participants': sorted_participants,
            'total_score': sum(p.get('cardsEarned', 0) for p in participants),
            'count': len(participants)
        }

        return stats