const keywordInput = document.getElementById("keyword");
const maxProductsInput = document.getElementById("maxProducts");
const openSearchButton = document.getElementById("openSearch");
const autoSaveButton = document.getElementById("autoSave");
const saveImagesButton = document.getElementById("saveImages");
const continueTaskButton = document.getElementById("continueTask");
const stopTaskButton = document.getElementById("stopTask");
const statusText = document.getElementById("status");

openSearchButton.addEventListener("click", async () => {
  const keyword = keywordInput.value.trim();
  if (!keyword) {
    setStatus("请先输入关键词。");
    return;
  }
  const url = `https://s.taobao.com/search?q=${encodeURIComponent(keyword)}`;
  await chrome.tabs.create({ url });
  setStatus(`已打开搜索页：${keyword}`);
});

saveImagesButton.addEventListener("click", async () => {
  saveImagesButton.disabled = true;
  setStatus("正在读取当前页面图片...");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) {
      setStatus("没有找到当前标签页。");
      return;
    }

    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectTaobaoImages,
    });

    if (!result?.images?.length) {
      setStatus("当前页面没有找到可保存的淘宝/天猫商品图片。");
      return;
    }

    const response = await chrome.runtime.sendMessage({
      type: "downloadImages",
      payload: result,
    });

    setStatus(`已开始下载 ${response.count} 张图片。\n请在 Chrome 下载内容或 Downloads/taobao-image-saver 中查看。`);
  } catch (error) {
    setStatus(`保存失败：${error.message || error}`);
  } finally {
    saveImagesButton.disabled = false;
  }
});

autoSaveButton.addEventListener("click", async () => {
  const keyword = keywordInput.value.trim();
  const maxProducts = Number.parseInt(maxProductsInput.value, 10) || 3;
  if (!keyword) {
    setStatus("请先输入关键词。");
    return;
  }
  autoSaveButton.disabled = true;
  setStatus("正在启动自动任务...");
  try {
    const response = await chrome.runtime.sendMessage({
      type: "startAutoSave",
      payload: { keyword, maxProducts },
    });
    setStatus(response.message || "任务已启动。");
  } catch (error) {
    setStatus(`启动失败：${error.message || error}`);
  } finally {
    autoSaveButton.disabled = false;
  }
});

continueTaskButton.addEventListener("click", async () => {
  const response = await chrome.runtime.sendMessage({ type: "continueAutoSave" });
  setStatus(response.message || "已继续。");
});

stopTaskButton.addEventListener("click", async () => {
  const response = await chrome.runtime.sendMessage({ type: "stopAutoSave" });
  setStatus(response.message || "已停止。");
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "status") {
    setStatus(message.message);
  }
});

chrome.storage.local.get("taskStatus").then(({ taskStatus }) => {
  if (taskStatus) setStatus(taskStatus);
});

function setStatus(message) {
  statusText.textContent = message;
  chrome.storage?.local?.set({ taskStatus: message }).catch(() => {});
}

function collectTaobaoImages() {
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
    const text = [
      img.className,
      img.id,
      parent?.className,
      parent?.id,
      ancestor?.className,
      ancestor?.id,
    ]
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
