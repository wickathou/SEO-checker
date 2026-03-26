from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any
import httpx
from bs4 import BeautifulSoup

app = FastAPI(
    title="SEO Preview API",
    description="Paste a URL, get SEO-relevant metadata back",
    version="0.2.0",
)

templates = Jinja2Templates(directory="src/templates")


class AnalyzeRequest(BaseModel):
    url: HttpUrl


class AnalyzeResponse(BaseModel):
    success: bool
    url: str
    status_code: Optional[int]
    meta: Dict[str, Optional[str]]
    raw: Dict[str, Any]


def extract_first(meta_tags, *candidates):
    for selector in candidates:
        el = meta_tags.select_one(selector)
        if el:
            content = el.get("content") or el.get("value") or el.get_text(strip=True)
            if content:
                return content.strip()
    return None


def extract_all(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    page_title = None
    if soup.title and soup.title.string:
        page_title = soup.title.string.strip()

    canonical = None
    canonical_link = soup.select_one("link[rel=canonical]")
    if canonical_link and canonical_link.get("href"):
        canonical = canonical_link["href"].strip()

    favicon = None
    fav_el = soup.select_one(
        'link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]'
    )
    if fav_el and fav_el.get("href"):
        favicon = fav_el["href"].strip()

    meta_description = extract_first(
        soup,
        'meta[name="description"]',
        'meta[property="og:description"]',
        'meta[name="twitter:description"]',
    )

    og_title = extract_first(
        soup,
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
    )

    og_image = extract_first(
        soup,
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'meta[name="twitter:image:src"]',
    )

    og_url = extract_first(
        soup,
        'meta[property="og:url"]',
        'meta[name="twitter:url"]',
    )

    og_type = extract_first(
        soup,
        'meta[property="og:type"]',
    )

    twitter_card = extract_first(
        soup,
        'meta[name="twitter:card"]',
    )

    twitter_site = extract_first(
        soup,
        'meta[name="twitter:site"]',
        'meta[name="twitter:creator"]',
    )

    robots = extract_first(
        soup,
        'meta[name="robots"]',
        'meta[name="googlebot"]',
    )

    return {
        "title": page_title,
        "meta_description": meta_description,
        "canonical": canonical,
        "favicon": favicon,
        "og_title": og_title,
        "og_description": meta_description,
        "og_image": og_image,
        "og_url": og_url,
        "og_type": og_type,
        "twitter_card": twitter_card,
        "twitter_site": twitter_site,
        "robots": robots,
    }


def extract_raw_debug(soup: BeautifulSoup) -> Dict[str, Any]:
    metas = []
    for tag in soup.find_all("meta"):
        metas.append(
            {
                "name": tag.get("name"),
                "property": tag.get("property"),
                "content": tag.get("content"),
            }
        )

    h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]

    html_el = soup.find("html")
    lang = html_el.get("lang").strip() if html_el and html_el.get("lang") else None

    return {
        "lang": lang,
        "h1": h1s,
        "meta_tags": metas[:50],
    }


async def fetch_and_parse(url: str):
    try:
        async with httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                )
            },
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch URL: {e}",
        )

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type:
        raise HTTPException(
            status_code=415,
            detail=f"URL did not return HTML (content-type: {content_type})",
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    meta_clean = extract_all(soup)
    raw_debug = extract_raw_debug(soup)

    return resp, meta_clean, raw_debug


# -------- API (JSON) --------

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    resp, meta_clean, raw_debug = await fetch_and_parse(str(req.url))

    return AnalyzeResponse(
        success=True,
        url=str(req.url),
        status_code=resp.status_code,
        meta=meta_clean,
        raw=raw_debug,
    )


# -------- Web UI --------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


@app.post("/analyze-form", response_class=HTMLResponse)
async def analyze_form(request: Request, url: str = Form(...)):
    resp, meta_clean, raw_debug = await fetch_and_parse(url)

    # We'll render result.html with all the parsed data
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "input_url": url,
            "status_code": resp.status_code,
            "meta": meta_clean,
            "raw": raw_debug,
        },
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}
