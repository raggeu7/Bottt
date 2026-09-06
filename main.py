import asyncio
import os
import re
import shutil
import urllib.parse

import discord
from discord import app_commands
from discord.ext import commands
from playwright.async_api import async_playwright


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TARGET_SITE_URL = os.getenv(
    "TARGET_SITE_URL", "https://example-arabic-cinema-site.com"
).rstrip("/")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


async def scrape_media_stream(query: str):
    found_media = {"url": None, "referer": None, "type": None}
    search_url = f"{TARGET_SITE_URL}/search?q={urllib.parse.quote(query)}"

    async with async_playwright() as p:
        chromium_path = (
            os.getenv("CHROMIUM_PATH")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome")
        )
        launch_options = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        }
        if chromium_path:
            launch_options["executable_path"] = chromium_path
            print(f"Chromium executable: {chromium_path}")
        else:
            print("Chromium executable not found on PATH; using Playwright default.")

        browser = await p.chromium.launch(**launch_options)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        async def handle_request(request):
            url = request.url
            if re.search(r"\.(m3u8|mp4)(\?|$)", url, re.IGNORECASE):
                if not found_media["url"]:
                    found_media["url"] = url
                    found_media["referer"] = request.headers.get(
                        "referer", TARGET_SITE_URL
                    )
                    found_media["type"] = "Direct Stream (m3u8/mp4)"

        page.on("request", handle_request)

        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

            first_result = page.locator(
                ".search-results .item a, .movie-card a"
            ).first
            if await first_result.count() > 0:
                await first_result.click()
                await page.wait_for_load_state("domcontentloaded")

            play_button = page.locator(
                "button.play-btn, .player-container iframe, #player"
            ).first
            if await play_button.count() > 0:
                await play_button.click(force=True)

            for _ in range(10):
                if found_media["url"]:
                    break
                await asyncio.sleep(0.5)

            if not found_media["url"]:
                for frame in page.frames:
                    if any(
                        marker in frame.url
                        for marker in ("player", "embed", "vidsrc")
                    ):
                        found_media["url"] = frame.url
                        found_media["referer"] = page.url
                        found_media["type"] = "Embed / iframe Server"
                        break

        except Exception as exc:
            print(f"[Error during scraping]: {exc}")
        finally:
            await context.close()
            await browser.close()

    return found_media


@bot.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح كـ: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"تم مزامنة {len(synced)} أمر سلاش.")
    except Exception as exc:
        print(f"خطأ أثناء مزامنة الأوامر: {exc}")


@bot.tree.command(
    name="watch",
    description="ابحث عن فيلم أو مسلسل واستخرج رابط المشغل المباشر",
)
@app_commands.describe(title="اسم الفيلم أو المسلسل")
async def watch(interaction: discord.Interaction, title: str):
    await interaction.response.defer(thinking=True)
    result = await scrape_media_stream(title)

    if result["url"]:
        embed = discord.Embed(
            title=f"نتائج البحث: {title}",
            color=discord.Color.green(),
            description="تم استخراج رابط المشغل المباشر بنجاح.",
        )
        embed.add_field(
            name="نوع السيرفر", value=f"`{result['type']}`", inline=False
        )
        embed.add_field(
            name="رابط المشغل", value=f"```{result['url']}```", inline=False
        )
        if result["referer"]:
            embed.add_field(
                name="Referer المطلوبة (لـ VLC / External Players)",
                value=f"`{result['referer']}`",
                inline=False,
            )
        embed.set_footer(text="استخدم الرابط في مشغل مثل VLC إذا كان نوعه m3u8")
        await interaction.followup.send(embed=embed)
    else:
        embed = discord.Embed(
            title="لم يتم العثور على رابط",
            description=f"تعذر استخراج رابط مباشر للعمل: **{title}**.",
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("خطأ: لم يتم العثور على DISCORD_TOKEN في متغيرات البيئة!")
    bot.run(DISCORD_TOKEN)
