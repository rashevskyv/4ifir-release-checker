import requests
import tempfile
import logging
from datetime import datetime
import os

from config import (
    GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, 
    REQUIRED_FILES, logger
)

def add_file_to_release(upload_url, file_path, file_name, headers):
    """Додати файл до існуючого релізу."""
    try:
        with open(file_path, 'rb') as file:
            upload_headers = headers.copy()
            upload_headers["Content-Type"] = "application/zip"
            
            upload_response = requests.post(
                f"{upload_url}?name={file_name}",
                headers=upload_headers,
                data=file
            )
            upload_response.raise_for_status()
        
        logger.info(f"Файл {file_name} успішно додано до релізу")
        return True
    except Exception as e:
        logger.error(f"Помилка додавання файлу {file_name} до релізу: {e}")
        return False

def get_all_releases():
    """Отримати всі релізи з GitHub."""
    try:
        releases_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
        
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        response = requests.get(releases_url, headers=headers)
        response.raise_for_status()
        
        releases = response.json()
        if not releases:
            logger.warning("Не знайдено жодного релізу на GitHub")
            return []
        
        return releases
    except Exception as e:
        logger.error(f"Помилка отримання релізів: {e}")
        return []

def get_latest_release():
    """Отримати останній реліз з GitHub."""
    releases = get_all_releases()
    if releases:
        # Останній реліз - перший у списку
        return releases[0]
    return None

def download_asset_from_github(asset_url, file_name):
    """Завантажити файл-ассет з GitHub релізу."""
    try:
        headers = {
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        # Створюємо тимчасовий файл для завантаження
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_path = temp_file.name
        
        # Завантажуємо файл
        response = requests.get(asset_url, headers=headers, stream=True)
        response.raise_for_status()
        
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"Файл {file_name} успішно завантажено з GitHub")
        return temp_path
    except Exception as e:
        logger.error(f"Помилка завантаження файлу {file_name} з GitHub: {e}")
        return None

def download_required_files_from_previous_releases():
    """Завантажити необхідні файли з попередніх релізів, шукаючи в усіх доступних релізах."""
    try:
        all_releases = get_all_releases()
        if not all_releases:
            logger.warning("Не знайдено жодного релізу для пошуку необхідних файлів")
            return {}
        
        downloaded_files = {}
        remaining_files = set(REQUIRED_FILES)
        
        # Проходимо по всіх релізах (від найновішого до найстаршого)
        for release in all_releases:
            # Якщо всі файли вже знайдено, виходимо з циклу
            if not remaining_files:
                break
                
            release_tag = release.get("tag_name", "невідома версія")
            
            for asset in release.get("assets", []):
                asset_name = asset.get("name")
                
                # Перевіряємо, чи цей файл потрібен і чи він ще не знайдений
                if asset_name in remaining_files:
                    logger.info(f"Знайдено необхідний файл {asset_name} в релізі {release_tag}")
                    
                    download_url = asset.get("url")
                    if download_url:
                        temp_path = download_asset_from_github(download_url, asset_name)
                        
                        if temp_path:
                            downloaded_files[asset_name] = {
                                "path": temp_path,
                                "name": asset_name
                            }
                            # Видаляємо файл з переліку тих, що ще потрібно знайти
                            remaining_files.remove(asset_name)
        
        # Перевіряємо, чи залишилися файли, які не вдалося знайти
        if remaining_files:
            logger.warning(f"Не вдалося знайти наступні файли в жодному з релізів: {', '.join(remaining_files)}")
        
        return downloaded_files
    except Exception as e:
        logger.error(f"Помилка при завантаженні файлів з релізів: {e}")
        return {}

def create_github_release(version: str, description: str, file_paths):
    """Створити реліз на GitHub і додати до нього файли."""
    # Спочатку створюємо реліз
    release_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    
    # Створюємо тег для релізу
    tag = f"v{version}"
    
    # Додаємо плашку з лічильником завантажень до опису
    download_badge = f"![GitHub release (latest by date)](https://img.shields.io/github/downloads/{GITHUB_OWNER}/{GITHUB_REPO}/{tag}/total)\n\n"
    enhanced_description = download_badge + description
    
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    data = {
        "tag_name": tag,
        "target_commitish": "main",
        "name": "4IFIR",  # Фіксована назва релізу
        "body": enhanced_description,
        "draft": False,
        "prerelease": False
    }
    
    try:
        # Створення релізу
        response = requests.post(release_url, headers=headers, json=data)
        response.raise_for_status()
        release_data = response.json()
        
        # Отримуємо URL для завантаження ассетів
        upload_url = release_data["upload_url"].split("{")[0]
        
        # Створюємо список для відстеження успішності завантаження всіх файлів
        all_uploads_successful = True
        
        # Завантаження всіх файлів як ассети
        for file_info in file_paths:
            file_path = file_info["path"]
            file_name = file_info["name"]
            
            success = add_file_to_release(upload_url, file_path, file_name, headers)
            if not success:
                all_uploads_successful = False
        
        if all_uploads_successful:
            logger.info(f"GitHub реліз v{version} успішно створено з усіма файлами")
        else:
            logger.warning(f"GitHub реліз v{version} створено, але деякі файли не були завантажені")
            
        return all_uploads_successful, release_data["html_url"]
    except Exception as e:
        logger.error(f"Помилка створення GitHub релізу: {e}")
        return False, None