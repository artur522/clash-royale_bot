import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

def test_api():
    """Тестирование подключения к API через прокси"""
    
    api_key = os.getenv("CR_API_TOKEN")
    use_proxy = os.getenv("USE_PROXY", "true").lower() == "true"
    
    if not api_key:
        print("❌ CR_API_TOKEN не найден в .env файле")
        sys.exit(1)
    
    # Выбираем URL в зависимости от настройки
    if use_proxy:
        base_url = "https://proxy.royaleapi.dev/v1"
        print("🌐 Использую RoyaleAPI Proxy")
    else:
        base_url = "https://api.clashroyale.com/v1"
        print("🌐 Использую официальный API")
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json'
    }
    
    print(f"\n🔗 URL: {base_url}")
    print(f"🔑 API Key: {api_key[:20]}...")
    
    # Тест 1: Получить список карт
    print("\n1. 📊 Получаю список карт...")
    try:
        response = requests.get(f"{base_url}/cards", headers=headers, timeout=15)
        print(f"   Статус: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Успех! Карт в игре: {len(data.get('items', []))}")
        elif response.status_code == 403:
            print(f"   ❌ Ошибка 403: Неверный ключ или IP не разрешен")
            print(f"   💡 Убедитесь что создали ключ с IP: 45.79.218.79")
            return False
        else:
            print(f"   ❌ Ошибка: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"   ❌ Ошибка запроса: {e}")
        return False
    
    # Тест 2: Получить информацию об игроке (если указан тег в .env)
    admin_tag = os.getenv("ADMIN_TAG")
    if admin_tag and admin_tag != "#YOUR_TAG_HERE":
        print(f"\n2. 👤 Получаю информацию об игроке {admin_tag}...")
        try:
            encoded_tag = requests.utils.quote(admin_tag)
            response = requests.get(
                f"{base_url}/players/{encoded_tag}",
                headers=headers,
                timeout=15
            )
            print(f"   Статус: {response.status_code}")
            
            if response.status_code == 200:
                player_data = response.json()
                print(f"   ✅ Успех! Игрок: {player_data.get('name')}")
                print(f"   🏆 Трофеи: {player_data.get('trophies', 0):,}")
            elif response.status_code == 404:
                print(f"   ⚠️ Игрок не найден. Проверьте тег.")
            else:
                print(f"   ❌ Ошибка: {response.text[:200]}")
                
        except Exception as e:
            print(f"   ❌ Ошибка запроса: {e}")
    
    # Тест 3: Получить информацию о клане (если указан тег в .env)
    clan_tag = os.getenv("CLAN_TAG")
    if clan_tag and clan_tag != "#YOUR_CLAN_TAG":
        print(f"\n3. 🏰 Получаю информацию о клане {clan_tag}...")
        try:
            encoded_tag = requests.utils.quote(clan_tag)
            response = requests.get(
                f"{base_url}/clans/{encoded_tag}",
                headers=headers,
                timeout=15
            )
            print(f"   Статус: {response.status_code}")
            
            if response.status_code == 200:
                clan_data = response.json()
                print(f"   ✅ Успех! Клан: {clan_data.get('name')}")
                print(f"   👥 Участников: {clan_data.get('members')}")
            elif response.status_code == 404:
                print(f"   ⚠️ Клан не найден. Проверьте тег.")
            else:
                print(f"   ❌ Ошибка: {response.text[:200]}")
                
        except Exception as e:
            print(f"   ❌ Ошибка запроса: {e}")
    
    print("\n" + "="*50)
    print("🎉 Все тесты завершены! API работает корректно.")
    print("Теперь можно запускать бота.")
    return True

if __name__ == "__main__":
    success = test_api()
    sys.exit(0 if success else 1)