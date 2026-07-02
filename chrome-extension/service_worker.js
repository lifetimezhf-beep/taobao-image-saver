chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "startAutoSave") {
    startAutoSave(message.payload).catch((error) => {
      setStatus(`任务启动失败：${error.message || error}`);
    });
    sendResponse({ message: "自动任务已启动。请保持 Chrome 打开。" });
    return true;
  }

  if (message?.type === "continueAutoSave") {
    taskState.waiting = false;
    sendResponse({ message: "已继续任务。" });
    return true;
  }

  if (message?.type === "stopAutoSave") {
    taskState.stop = true;
    taskState.waiting = false;
    sendResponse({ message: "正在停止任务。" });
    return true;
  }

  if (message?.type !== "downloadImages") return false;

  const { title, images } = message.payload;
  const folder = `taobao-image-saver/${sanitizeFileName(title)}`;
  let count = 0;

  for (const image of images) {
    count += 1;
    const suffix = extensionFromUrl(image.url);
    const filename = `${folder}/${image.kind}_${String(count).padStart(3, "0")}${suffix}`;
    chrome.downloads.download({
      url: image.url,
      filename,
      conflictAction: "uniquify",
      saveAs: false,
    });
  }

  const metadataUrl = metadataDataUrl({ title, capturedAt: new Date().toISOString(), images });
  chrome.downloads.download({
    url: metadataUrl,
    filename: `${folder}/metadata.json`,
    conflictAction: "uniquify",
    saveAs: false,
  });

  sendResponse({ count });
  return true;
});

const taskState = {
  stop: false,
  waiting: false,
  running: false,
};

async function startAutoSave({ keyword, maxProducts }) {
  if (taskState.running) {
    await setStatus("已有自动任务正在运行。");
    return;
  }
  taskState.running = true;
  taskState.stop = false;
  taskState.waiting = false;
  try {
    await setStatus(`开始搜索：${keyword}`);
    const searchUrl = `https://s.taobao.com/search?q=${encodeURIComponent(keyword)}`;
    const tab = await chrome.tabs.create({ url: searchUrl, active: true });
    await waitForTabLoaded(tab.id);
    await waitForManualIfNeeded(tab.id, "搜索页需要登录或验证。请手动处理后点击扩展里的“我已处理验证，继续”。");
    if (taskState.stop) return await setStatus("任务已停止。");

    await slowScroll(tab.id, 5);
    await setStatus("正在收集搜索结果商品链接...");
    const [{ result: links }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectProductLinks,
    });

    const productLinks = Array.from(new Map((links || []).map((item) => [item.url, item])).values()).slice(
      0,
      Math.max(1, Math.min(maxProducts || 3, 20)),
    );

    if (!productLinks.length) {
      return await setStatus("没有找到商品链接。请确认搜索结果已正常加载。");
    }

    await setStatus(`找到 ${productLinks.length} 个商品，开始逐个保存。`);
    let success = 0;
    let failed = 0;

    for (let index = 0; index < productLinks.length; index += 1) {
      if (taskState.stop) break;
      const product = productLinks[index];
      await setStatus(`打开商品 ${index + 1}/${productLinks.length}：${product.title || product.url}`);
      await chrome.tabs.update(tab.id, { url: product.url, active: true });
      await waitForTabLoaded(tab.id);
      await waitForManualIfNeeded(tab.id, "商品页需要登录或验证。请手动处理后点击扩展里的“我已处理验证，继续”。");
      if (taskState.stop) break;

      await slowScroll(tab.id, 6);
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: collectTaobaoImagesForBackground,
      });

      if (result?.images?.length) {
        downloadImagePayload(result);
        success += 1;
        await setStatus(`已保存商品 ${index + 1}/${productLinks.length}，图片 ${result.images.length} 张。`);
      } else {
        failed += 1;
        await setStatus(`商品 ${index + 1} 未找到可保存图片。`);
      }
      await delay(randomDelay(2500, 5000));
    }

    await setStatus(`任务完成：成功 ${success}，失败 ${failed}。`);
  } catch (error) {
    await setStatus(`任务出错：${error.message || error}`);
  } finally {
    taskState.running = false;
  }
}

async function setStatus(message) {
  await chrome.storage.local.set({ taskStatus: message }).catch(() => {});
  chrome.runtime.sendMessage({ type: "status", message }).catch(() => {});
}

async function waitForTabLoaded(tabId) {
  for (let i = 0; i < 90; i += 1) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return;
    await delay(1000);
  }
}

async function waitForManualIfNeeded(tabId, message) {
  if (!(await pageNeedsManualCheck(tabId))) return;
  taskState.waiting = true;
  await setStatus(message);
  while (taskState.waiting && !taskState.stop) {
    await delay(1000);
  }
}

async function pageNeedsManualCheck(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const url = (tab.url || "").toLowerCase();
  if (/(login|verify|captcha|passport)/.test(url)) return true;
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const text = document.body?.innerText || "";
      return /(登录|验证码|滑块|安全验证|验证失败|请拖动)/.test(text);
    },
  });
  return Boolean(result);
}

async function slowScroll(tabId, rounds) {
  for (let i = 0; i < rounds; i += 1) {
    if (taskState.stop) return;
    await chrome.scripting.executeScript({
      target: { tabId },
      func: () => window.scrollBy({ top: Math.floor(650 + Math.random() * 450), behavior: "smooth" }),
    });
    await delay(randomDelay(900, 1600));
  }
}

function collectProductLinks() {
  const candidates = Array.from(document.querySelectorAll("a[href]"))
    .map((anchor) => ({
      url: normalizeProductUrl(anchor.href),
      title: (anchor.innerText || anchor.title || "").trim().split("\n")[0].slice(0, 120),
    }))
    .filter((item) => item.url);

  return candidates;

  function normalizeProductUrl(rawUrl) {
    try {
      const parsed = new URL(rawUrl, location.href);
      const directProduct =
        /item\.taobao\.com\/item\.htm|detail\.tmall\.com\/item\.htm|detail\.tmall\.hk/i.test(parsed.href);
      if (directProduct) return canonical(parsed);

      const embedded = parsed.searchParams.get("url") || parsed.searchParams.get("targetUrl") || parsed.searchParams.get("redirectUrl");
      if (embedded) {
        const decoded = new URL(decodeURIComponent(embedded), location.href);
        if (/item\.taobao\.com\/item\.htm|detail\.tmall\.com\/item\.htm|detail\.tmall\.hk/i.test(decoded.href)) {
          return canonical(decoded);
        }
      }

      const id = parsed.searchParams.get("id") || parsed.searchParams.get("itemId") || parsed.searchParams.get("item_id");
      if (id && /taobao|tmall|alicdn/i.test(parsed.hostname)) {
        return `https://item.taobao.com/item.htm?id=${encodeURIComponent(id)}`;
      }
    } catch {
      return "";
    }
    return "";
  }

  function canonical(parsed) {
    const id = parsed.searchParams.get("id");
    if (id) parsed.search = `?id=${id}`;
    parsed.hash = "";
    return parsed.href;
  }
}

function collectTaobaoImagesForBackground() {
  const imageAttrs = ["src", "data-src", "data-ks-lazyload", "data-lazyload", "data-original", "data-img"];
  const seen = new Set();
  const images = [];

  for (const img of Array.from(document.images)) {
    const kind = classifyImage(img);
    for (const url of urlsFromImage(img)) {
      if (!looksLikeProductImage(url)) continue;
      const cleanUrl = stripImageSizeSuffix(url);
      const key = `${kind}:${cleanUrl}`;
      if (seen.has(key)) continue;
      seen.add(key);
      images.push({ url: cleanUrl, kind });
    }
  }

  return {
    title: sanitizeName(document.title || "淘宝商品"),
    pageUrl: location.href,
    images,
  };

  function urlsFromImage(img) {
    const urls = [];
    const srcset = img.getAttribute("srcset");
    if (srcset) {
      const picked = pickLargestFromSrcset(srcset);
      if (picked) urls.push(picked);
    }
    for (const attr of imageAttrs) {
      const value = img.getAttribute(attr);
      if (!value || value.startsWith("data:image")) continue;
      urls.push(new URL(value, location.href).href);
    }
    return urls;
  }

  function pickLargestFromSrcset(srcset) {
    const candidates = srcset
      .split(",")
      .map((part) => {
        const bits = part.trim().split(/\s+/);
        const width = bits[1]?.endsWith("w") ? Number.parseInt(bits[1], 10) || 0 : 0;
        return { url: bits[0] ? new URL(bits[0], location.href).href : "", width };
      })
      .filter((item) => item.url);
    candidates.sort((a, b) => b.width - a.width);
    return candidates[0]?.url || "";
  }

  function classifyImage(img) {
    const parent = img.parentElement;
    const ancestor = img.closest("[class], [id]");
    const text = [img.className, img.id, parent?.className, parent?.id, ancestor?.className, ancestor?.id]
      .join(" ")
      .toLowerCase();
    if (/(desc|detail|description|content|rich-text)/.test(text)) return "detail";
    if (/(main|gallery|thumb|slider|carousel|pic)/.test(text)) return "main";
    return "other";
  }

  function looksLikeProductImage(url) {
    try {
      const parsed = new URL(url);
      const host = parsed.hostname.toLowerCase();
      const path = parsed.pathname.toLowerCase();
      return (
        /\.(jpg|jpeg|png|webp|gif|avif)(_|\.|$)/.test(path) &&
        /(alicdn\.com|taobaocdn\.com|tbcdn\.cn|taobao\.com)/.test(host)
      );
    } catch {
      return false;
    }
  }

  function stripImageSizeSuffix(url) {
    const parsed = new URL(url);
    parsed.pathname = parsed.pathname.replace(/_(\d+x\d+(?:q\d+)?|sum|q\d+|webp)(?:\.[a-zA-Z0-9]+)?$/, "");
    return parsed.href;
  }

  function sanitizeName(value) {
    return (value || "淘宝商品")
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80) || "淘宝商品";
  }
}

function downloadImagePayload(payload) {
  const { title, images } = payload;
  const folder = `taobao-image-saver/${sanitizeFileName(title)}`;
  let count = 0;

  for (const image of images) {
    count += 1;
    chrome.downloads.download({
      url: image.url,
      filename: `${folder}/${image.kind}_${String(count).padStart(3, "0")}${extensionFromUrl(image.url)}`,
      conflictAction: "uniquify",
      saveAs: false,
    });
  }

  const metadataUrl = metadataDataUrl({ title, capturedAt: new Date().toISOString(), images });
  chrome.downloads.download({
    url: metadataUrl,
    filename: `${folder}/metadata.json`,
    conflictAction: "uniquify",
    saveAs: false,
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelay(min, max) {
  return Math.floor(min + Math.random() * (max - min));
}

function sanitizeFileName(value) {
  return (value || "淘宝商品")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "淘宝商品";
}

function extensionFromUrl(url) {
  const path = new URL(url).pathname.toLowerCase();
  for (const suffix of [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"]) {
    if (path.includes(suffix)) return suffix === ".jpeg" ? ".jpg" : suffix;
  }
  return ".jpg";
}

function metadataDataUrl(metadata) {
  return `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(metadata, null, 2))}`;
}
