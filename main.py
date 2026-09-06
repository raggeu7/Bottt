import asyncio
import re
import urllib.parse
import discord
from discord import app_commands
from discord.ext import commands
from playwright.async_api import async_playwright

# ==========================================================
# الإعدادات الأساسية للبوت والموقع المستهدف
# ==========================================================
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"  # استبدله بتوكن البوت الخاص بك
TARGET_SITE_URL = "https://example-arabic-cinema-site.com"  # استبدله برابط موقع السينما المستهدف

# إعداد كائن البوت مع صلاحيات Slash Commands
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ==========================================================
# دالة استخراج الروابط باستخدام Playwright (Async)
# ==========================================================
async def scrape_media_stream(query: str):
    """تفتح متصفح خفي، تبحث عن العنوان، وتنصت للشبكة لالتقاط روابط التشغيل."""
    found_media = {"url": None, "referer": None, "type": None}
    search_url = f"{TARGET_SITE_URL}/search?q={urllib.parse.quote(query)}"

    async with async_playwright() as p:
        # تشغيل متصفح Chromium في الوضع الخفي مع محاكاة متصفح حقيقي لتفادي الحظر
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # معالج أحداث حركة الشبكة (Network Listener)
        async def handle_request(request):
            url = request.url
            # البحث عن امتدادات البث المباشر .m3u8 أو .mp4
            if re.search(r"\.(m3u8|mp4)(\?|$)", url, re.IGNORECASE):
                if not found_media["url"]:
                    found_media["url"] = url
                    found_media["referer"] = request.headers.get("referer", TARGET_SITE_URL)
                    found_media["type"] = "Direct Stream (m3u8/mp4)"

        # تسجيل التنصت على طلبات الشبكة
        page.on("request", handle_request)

        try:
            # 1. الانتقال إلى صفحة البحث
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

            # 2. النقر على النتيجة الأولى (يتم تعديل الـ Selector حسب تصميم الموقع)
            first_result = page.locator(".search-results .item a, .movie-card a").first
            if await first_result.count() > 0:
                await first_result.click()
                await page.wait_for_load_state("domcontentloaded")

            # 3. محاولة النقر على زر التشغيل أو السيرفر للبدء في تحميل المشغل
            play_button = page.locator("button.play-btn, .player-container iframe, #player").first
            if await play_button.count() > 0:
                await play_button.click(force=True)

            # 4. البحث عن روابط iframe إذا لم يتم التقاط رابط m3u8/mp4 مباشر
            for _ in range(10):  # الانتظار لمدة تصل إلى 5 ثوانٍ لالتقاط الطلبات
                if found_media["url"]:
                    break
                await asyncio.sleep(0.5)

            if not found_media["url"]:
                # إذا لم نجد ملف ميديا مباشر، نتحقق من وجود سيرفر iframe
                iframes = page.frames
                for frame in iframes:
                    if "player" in frame.url or "embed" in frame.url or "vidsrc" in frame.url:
                        found_media["url"] = frame.url
                        found_media["referer"] = page.url
                        found_media["type"] = "Embed / iframe Server"
                        break

        except Exception as e:
            print(f"[Error during scraping]: {e}")
        finally:
            # إغلاق المتصفح فوراً لتوفير موارد المخدم
            await browser.close()

    return found_media


# ==========================================================
# أحداث البوت وأوامر السلاش (Slash Commands)
# ==========================================================
@bot.event
async def on_ready():
    """تزامن أوامر السلاش عند إقلاع البوت."""
    print(f"تم تسجيل الدخول بنجاح كـ: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"تم مزامنة {len(synced)} أمر سلاش.")
    except Exception as e:
        print(f"خطأ أثناء مزامنة الأوامر: {e}")


@bot.tree.command(name="watch", description="ابحث عن فيلم أو مسلسل واستخرج رابط المشغل المباشر")
@app_commands.describe(title="اسم الفيلم أو المسلسل (مثال: آل التنين)")
async def watch(interaction: discord.Interaction, title: str):
    # إعلام المستخدم أن البوت يعالج الطلب (لتجنب انتهاء مهلة 3 ثوانٍ في ديسكورد)
    await interaction.response.defer(thinking=True)

    # استدعاء دالة الكشط
    result = await scrape_media_stream(title)

    if result["url"]:
        # بناء الـ Embed عند العثور على الرابط
        embed = discord.Embed(
            title=f"🎬 نتائج البحث: {title}",
            color=discord.Color.green(),
            description="تم استخراج رابط المشغل المباشر بنجاح."
        )
        embed.add_field(name="نوع السيرفر", value=f"`{result['type']}`", inline=False)
        embed.add_field(name="رابط المشغل", value=f"```{result['url']}```", inline=False)
        
        if result["referer"]:
            embed.add_field(
                name="Referer المطلوبة (لـ VLC / External Players)",
                value=f"`{result['referer']}`",
                inline=False
            )
        
        embed.set_footer(text="استخدم الرابط في مشغل مثل VLC إذا كان نوعه m3u8")
        await interaction.followup.send(embed=embed)
    else:
        # رسالة الخطأ أو عدم العثور على نتائج
        embed = discord.Embed(
            title="❌ لم يتم العثور على رابط",
            description=f"تعذر استخراج رابط مباشر للعمل: **{title}**. قد يكون الموقع يحتاج لتحديث selectors أو أن السيرفر غير متوفر.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)


# ==========================================================
# تشغيل البوت
# ==========================================================
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
