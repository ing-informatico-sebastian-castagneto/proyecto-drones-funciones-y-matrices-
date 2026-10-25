"use strict";

const fileInput = document.querySelector("#file-input");
const demoButton = document.querySelector("#demo-button");
const sourceImage = document.querySelector("#source-image");
const sourceEmpty = document.querySelector("#source-empty");
const sourceDimensions = document.querySelector("#source-dimensions");
const resultImage = document.querySelector("#result-image");
const resultEmpty = document.querySelector("#result-empty");
const resultDimensions = document.querySelector("#result-dimensions");
const resultStatus = document.querySelector("#result-status");
const focusPicker = document.querySelector("#focus-picker");
const focusMarker = document.querySelector("#focus-marker");
const sourceFrame = document.querySelector("#source-frame");
const zoomInput = document.querySelector("#zoom-input");
const gammaInput = document.querySelector("#gamma-input");
const zoomValue = document.querySelector("#zoom-value");
const gammaValue = document.querySelector("#gamma-value");
const xInput = document.querySelector("#x-input");
const yInput = document.querySelector("#y-input");
const processButton = document.querySelector("#process-button");
const processingOverlay = document.querySelector("#processing-overlay");
const downloadLink = document.querySelector("#download-link");
const errorMessage = document.querySelector("#error-message");
const serviceStatus = document.querySelector("#service-status");
const serviceStatusText = document.querySelector("#service-status-text");
const uploadHelp = document.querySelector("#upload-help");
const liveButton = document.querySelector("#live-button");
const liveStateText = document.querySelector("#live-state-text");
const liveFrameState = document.querySelector("#live-frame-state");
const analysisStatus = document.querySelector("#analysis-status");
const imageMetrics = document.querySelector("#image-metrics");
const assistantReports = document.querySelector("#assistant-reports");
const codeInput = document.querySelector("#code-input");
const codeAnalysisStatus = document.querySelector("#code-analysis-status");
const codeAnalysisMetrics = document.querySelector("#code-analysis-metrics");
const codeCharacterCount = document.querySelector("#code-character-count");
const codeAssistantReports = document.querySelector("#code-assistant-reports");
const cameraHeight = document.querySelector("#camera-height");
const cameraTilt = document.querySelector("#camera-tilt");
const cameraFov = document.querySelector("#camera-fov");
const measureButton = document.querySelector("#measure-button");
const measurementResult = document.querySelector("#measurement-result");

let sourceBlob = null;
let sourceUrl = null;
let resultUrl = null;
let sourceName = "aerozoom-mejorada.png";
let activeRequest = null;
let processingTimer = null;
let appConfig = null;
let sourceSelectionId = 0;
let liveInterval = null;
let liveFrameIndex = 0;
let liveFrameLoading = false;
let liveFrameController = null;
let liveViewEnabled = false;
let measurementRequestId = 0;
let codeReviewTimer = null;
let codeReviewController = null;

function setError(message = "") {
  errorMessage.textContent = message;
  errorMessage.hidden = !message;
}

function setServiceStatus(online, message) {
  serviceStatus.classList.toggle("is-online", online);
  serviceStatus.classList.toggle("is-offline", !online);
  serviceStatusText.textContent = message;
}

function updateControlLabels() {
  zoomValue.value = `${Number(zoomInput.value).toFixed(1)}×`;
  gammaValue.value = Number(gammaInput.value).toFixed(1);
}

function revokeUrl(url) {
  if (url) URL.revokeObjectURL(url);
}

function updateFocusMarker() {
  if (!sourceBlob || !sourceImage.naturalWidth) return;

  const frame = sourceFrame.getBoundingClientRect();
  const scale = Math.min(
    frame.width / sourceImage.naturalWidth,
    frame.height / sourceImage.naturalHeight,
  );
  const renderedWidth = sourceImage.naturalWidth * scale;
  const renderedHeight = sourceImage.naturalHeight * scale;
  const left = (frame.width - renderedWidth) / 2
    + (Number(xInput.value) / sourceImage.naturalWidth) * renderedWidth;
  const top = (frame.height - renderedHeight) / 2
    + (Number(yInput.value) / sourceImage.naturalHeight) * renderedHeight;

  focusMarker.style.left = `${left}px`;
  focusMarker.style.top = `${top}px`;
}

function updateCenterInputs(x, y) {
  xInput.value = String(x);
  yInput.value = String(y);
  updateFocusMarker();
}

function addMetric(container, label, value) {
  const item = document.createElement("div");
  item.className = "measurement-value";
  const itemLabel = document.createElement("span");
  itemLabel.textContent = label;
  const itemValue = document.createElement("strong");
  itemValue.textContent = value;
  item.append(itemLabel, itemValue);
  container.append(item);
}

function renderAssistantReports(reports, container = assistantReports) {
  const fragment = document.createDocumentFragment();
  reports.forEach((report) => {
    const card = document.createElement("article");
    card.className = "assistant-report";
    const title = document.createElement("strong");
    title.textContent = `${report.assistant} · ${report.role}`;
    const summary = document.createElement("p");
    summary.textContent = report.summary;
    const recommendation = document.createElement("p");
    recommendation.textContent = report.recommendation;
    card.append(title, summary, recommendation);
    fragment.append(card);
  });
  container.replaceChildren(fragment);
}

async function reviewCode() {
  const source = codeInput.value;
  if (!source.trim()) {
    codeAnalysisStatus.textContent = "ESPERANDO CÓDIGO";
    codeAnalysisMetrics.textContent = "Escribe o pega código para comenzar.";
    return;
  }

  codeReviewController?.abort();
  const controller = new AbortController();
  codeReviewController = controller;
  codeAnalysisStatus.textContent = "REVISANDO";
  try {
    const response = await fetch("/api/v1/assistants/review-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(await readApiError(response));
    const report = await response.json();
    if (codeReviewController !== controller) return;
    const metrics = report.metrics;
    codeAnalysisMetrics.textContent = report.syntax_valid
      ? `${metrics.lines} líneas · ${metrics.functions} funciones · ${metrics.branches} ramas · ${metrics.long_functions} funciones largas · ${metrics.untyped_functions} sin tipos completos`
      : report.syntax_error;
    codeAnalysisStatus.textContent = report.syntax_valid
      ? "2 REVISIONES LISTAS"
      : "SINTAXIS A REVISAR";
    renderAssistantReports(report.assistants, codeAssistantReports);
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")
      && codeReviewController === controller) {
      codeAnalysisStatus.textContent = "REVISIÓN NO DISPONIBLE";
      codeAnalysisMetrics.textContent = formatError(
        error,
        "No fue posible revisar el fragmento Python.",
      );
    }
  } finally {
    if (codeReviewController === controller) codeReviewController = null;
  }
}

function scheduleCodeReview() {
  const length = codeInput.value.length;
  codeCharacterCount.textContent = `${length.toLocaleString("es-CL")} caracteres`;
  codeReviewController?.abort();
  window.clearTimeout(codeReviewTimer);

  if (appConfig && length > appConfig.assistants.max_source_chars) {
    codeAnalysisStatus.textContent = "FRAGMENTO DEMASIADO LARGO";
    codeAnalysisMetrics.textContent = `Límite: ${appConfig.assistants.max_source_chars.toLocaleString("es-CL")} caracteres.`;
    return;
  }

  codeReviewTimer = window.setTimeout(reviewCode, 600);
}

async function analyzeFrame(blob, selectionId) {
  if (!appConfig?.assistants) return;
  analysisStatus.textContent = "ANALIZANDO";
  const form = new FormData();
  form.append("file", blob, "cuadro.png");
  try {
    const response = await fetch("/api/v1/assistants/analyze", {
      method: "POST",
      body: form,
    });
    if (!response.ok) throw new Error(await readApiError(response));
    const report = await response.json();
    if (selectionId !== sourceSelectionId) return;
    imageMetrics.textContent = `${report.metrics.width} × ${report.metrics.height} px · luz ${report.metrics.brightness}/255 · contraste ${report.metrics.contrast} · nitidez ${report.metrics.sharpness} · sombras ${report.metrics.shadow_percent}%`;
    renderAssistantReports(report.assistants);
    analysisStatus.textContent = "2 ANÁLISIS LISTOS";
  } catch (error) {
    if (selectionId === sourceSelectionId) {
      analysisStatus.textContent = "ANÁLISIS NO DISPONIBLE";
      imageMetrics.textContent = formatError(error, "No fue posible analizar el cuadro.");
    }
  }
}

async function calculateMeasurement() {
  if (!sourceImage.naturalWidth || !sourceImage.naturalHeight) return;
  const requestId = ++measurementRequestId;
  const body = {
    image_width: sourceImage.naturalWidth,
    image_height: sourceImage.naturalHeight,
    pixel_x: Number(xInput.value),
    pixel_y: Number(yInput.value),
    camera_height_m: Number(cameraHeight.value),
    tilt_deg: Number(cameraTilt.value),
    vertical_fov_deg: Number(cameraFov.value),
  };
  if (!Number.isInteger(body.pixel_x) || !Number.isInteger(body.pixel_y)
    || !Number.isFinite(body.camera_height_m) || body.camera_height_m <= 0
    || !Number.isFinite(body.tilt_deg) || !Number.isFinite(body.vertical_fov_deg)) {
    return;
  }

  measureButton.disabled = true;
  try {
    const response = await fetch("/api/v1/measure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(await readApiError(response));
    const measurement = await response.json();
    if (requestId !== measurementRequestId) return;
    const values = document.createElement("div");
    values.className = "measurement-grid";
    addMetric(values, "Distancia en suelo", `${measurement.ground_distance_m} m`);
    addMetric(values, "Distancia inclinada", `${measurement.slant_distance_m} m`);
    addMetric(values, "Desplazamiento lateral", `${measurement.right_offset_m} m`);
    addMetric(values, "Adelante de cámara", `${measurement.forward_offset_m} m`);
    addMetric(values, "Ángulo de depresión", `${measurement.depression_angle_deg}°`);
    addMetric(values, "Rumbo relativo", `${measurement.camera_relative_bearing_deg}°`);
    measurementResult.replaceChildren(values);
  } catch (error) {
    if (requestId !== measurementRequestId) return;
    const message = document.createElement("span");
    message.className = "measurement-empty";
    message.textContent = formatError(error, "No fue posible calcular esta medición.");
    measurementResult.replaceChildren(message);
  } finally {
    if (requestId === measurementRequestId) measureButton.disabled = false;
  }
}

function scheduleProcessing() {
  if (!sourceBlob) return;
  window.clearTimeout(processingTimer);
  processingTimer = window.setTimeout(processImage, 350);
}

async function setSource(blob, name, selectionId) {
  if (selectionId !== sourceSelectionId) return;

  activeRequest?.abort();
  window.clearTimeout(processingTimer);
  const nextUrl = URL.createObjectURL(blob);
  const image = new Image();
  image.src = nextUrl;

  try {
    await image.decode();
  } catch {
    revokeUrl(nextUrl);
    if (selectionId !== sourceSelectionId) return;
    throw new Error("El archivo no se pudo leer como imagen.");
  }

  if (selectionId !== sourceSelectionId) {
    revokeUrl(nextUrl);
    return;
  }

  if (appConfig && (
    image.naturalWidth > appConfig.upload.max_image_dimension
    || image.naturalHeight > appConfig.upload.max_image_dimension
    || image.naturalWidth * image.naturalHeight > appConfig.upload.max_image_pixels
  )) {
    revokeUrl(nextUrl);
    throw new Error(
      `La imagen supera el máximo de ${appConfig.upload.max_image_dimension} px por lado o ${appConfig.upload.max_image_pixels.toLocaleString("es-CL")} píxeles.`,
    );
  }

  revokeUrl(sourceUrl);
  sourceUrl = nextUrl;
  sourceBlob = blob;
  sourceImage.src = sourceUrl;
  sourceImage.alt = `Imagen original: ${name}`;
  sourceImage.hidden = false;
  sourceEmpty.hidden = true;
  focusPicker.hidden = false;
  focusMarker.hidden = false;
  sourceDimensions.textContent = `${image.naturalWidth} × ${image.naturalHeight}`;
  sourceName = `${name.replace(/\.[^.]+$/, "")}-mejorada.png`;
  revokeUrl(resultUrl);
  resultUrl = null;
  resultImage.removeAttribute("src");
  resultImage.hidden = true;
  resultEmpty.hidden = false;
  resultStatus.textContent = "SIN PROCESAR";
  resultStatus.classList.remove("is-ready");
  resultDimensions.textContent = "Mantiene las dimensiones originales.";
  downloadLink.hidden = true;
  xInput.max = String(image.naturalWidth - 1);
  yInput.max = String(image.naturalHeight - 1);
  updateCenterInputs(Math.floor(image.naturalWidth / 2), Math.floor(image.naturalHeight / 2));
  processButton.disabled = false;
  measureButton.disabled = false;
  measurementResult.replaceChildren(
    Object.assign(document.createElement("span"), {
      className: "measurement-empty",
      textContent: "Selecciona un punto para ver su estimación.",
    }),
  );
  setError();
  scheduleProcessing();
  void analyzeFrame(blob, selectionId);
  if (!liveViewEnabled) {
    liveFrameState.textContent = "Cuadro cargado · fuente estática.";
  }
}

async function readApiError(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Fall through to a status-based message if the response is not JSON.
  }
  return `El servicio respondió con el estado ${response.status}.`;
}

function formatError(error, fallback) {
  return error instanceof Error && error.message
    ? error.message
    : fallback;
}

async function processImage() {
  if (!sourceBlob) return;
  activeRequest?.abort();

  const controller = new AbortController();
  activeRequest = controller;
  processButton.disabled = true;
  processButton.textContent = "Procesando…";
  processingOverlay.hidden = false;
  resultEmpty.hidden = true;
  resultImage.hidden = true;
  downloadLink.hidden = true;
  resultStatus.textContent = "PROCESANDO";
  resultStatus.classList.remove("is-ready");
  setError();

  const params = new URLSearchParams({
    zoom_factor: zoomInput.value,
    gamma: gammaInput.value,
    x: xInput.value,
    y: yInput.value,
  });
  const form = new FormData();
  form.append("file", sourceBlob, "imagen.png");

  try {
    const response = await fetch(`/api/v1/process?${params}`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(await readApiError(response));

    const nextUrl = URL.createObjectURL(await response.blob());
    if (activeRequest !== controller) {
      revokeUrl(nextUrl);
      return;
    }
    revokeUrl(resultUrl);
    resultUrl = nextUrl;
    resultImage.src = resultUrl;
    resultImage.hidden = false;
    resultEmpty.hidden = true;
    const width = response.headers.get("X-Image-Width");
    const height = response.headers.get("X-Image-Height");
    resultDimensions.textContent = width && height
      ? `Resultado ${width} × ${height} px · zoom ${Number(zoomInput.value).toFixed(1)}×`
      : "Mantiene las dimensiones originales.";
    resultStatus.textContent = "MEJORADA";
    resultStatus.classList.add("is-ready");
    downloadLink.href = resultUrl;
    downloadLink.download = sourceName;
    downloadLink.hidden = false;
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")
      && activeRequest === controller) {
      setError(formatError(error, "No se pudo procesar la imagen."));
      resultStatus.textContent = "ERROR";
      resultStatus.classList.remove("is-ready");
    }
  } finally {
    if (activeRequest === controller) {
      activeRequest = null;
      processButton.disabled = !sourceBlob;
      processButton.innerHTML = 'Aplicar mejora <span aria-hidden="true">→</span>';
      processingOverlay.hidden = true;
    }
  }
}

async function loadDemo() {
  stopLiveView();
  const selectionId = ++sourceSelectionId;
  activeRequest?.abort();
  window.clearTimeout(processingTimer);
  demoButton.disabled = true;
  setError();
  try {
    const response = await fetch("/api/v1/demo/source");
    if (!response.ok) throw new Error(await readApiError(response));
    await setSource(await response.blob(), "escena-nocturna.png", selectionId);
  } catch (error) {
    setError(formatError(error, "No se pudo cargar la imagen de ejemplo."));
  } finally {
    demoButton.disabled = false;
  }
}

function stopLiveView() {
  liveViewEnabled = false;
  window.clearInterval(liveInterval);
  liveInterval = null;
  liveFrameController?.abort();
  liveFrameController = null;
  liveFrameLoading = false;
  liveButton.classList.remove("is-running");
  liveButton.setAttribute("aria-pressed", "false");
  liveStateText.textContent = "Iniciar vista simulada";
  liveFrameState.textContent = "Cuadro detenido. Fuente: simulación local.";
}

async function requestLiveFrame() {
  if (!liveViewEnabled || liveFrameLoading || activeRequest) return;
  const selectionId = ++sourceSelectionId;
  const frameIndex = liveFrameIndex;
  const controller = new AbortController();
  liveFrameController = controller;
  liveFrameLoading = true;
  liveFrameState.textContent = `Recibiendo cuadro ${frameIndex + 1} · simulación local`;
  try {
    const response = await fetch(`/api/v1/live/frame?frame=${frameIndex}`, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await readApiError(response));
    await setSource(await response.blob(), `simulacion-${frameIndex + 1}.png`, selectionId);
    if (liveViewEnabled && selectionId === sourceSelectionId) {
      liveFrameIndex = (frameIndex + 1) % 80;
      liveFrameState.textContent = `EN VIVO · cuadro ${frameIndex + 1} · simulación local (sin cámara)`;
    }
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")
      && liveViewEnabled && selectionId === sourceSelectionId) {
      setError(formatError(error, "No se pudo recibir el cuadro en tiempo real."));
      liveFrameState.textContent = "Flujo simulado interrumpido.";
    }
  } finally {
    if (liveFrameController === controller) {
      liveFrameController = null;
      liveFrameLoading = false;
    }
  }
}

function startLiveView() {
  if (!appConfig?.live_view.enabled || liveViewEnabled) return;
  liveViewEnabled = true;
  liveButton.classList.add("is-running");
  liveButton.setAttribute("aria-pressed", "true");
  liveStateText.textContent = "Pausar vista simulada";
  void requestLiveFrame();
  liveInterval = window.setInterval(
    requestLiveFrame,
    appConfig.live_view.interval_ms,
  );
}

fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (!file) return;
  stopLiveView();
  const selectionId = ++sourceSelectionId;
  activeRequest?.abort();
  window.clearTimeout(processingTimer);
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    setError("Formato no compatible. Selecciona una imagen PNG, JPG o WebP.");
    return;
  }
  if (appConfig && file.size > appConfig.upload.max_bytes) {
    const maxMegabytes = appConfig.upload.max_bytes / (1024 * 1024);
    setError(`La imagen supera el límite de ${maxMegabytes.toLocaleString("es-CL")} MB.`);
    return;
  }

  try {
    await setSource(file, file.name, selectionId);
  } catch (error) {
    setError(formatError(error, "No se pudo cargar la imagen."));
  }
});

demoButton.addEventListener("click", loadDemo);
processButton.addEventListener("click", processImage);
liveButton.addEventListener("click", () => {
  if (liveViewEnabled) {
    sourceSelectionId += 1;
    stopLiveView();
  } else {
    startLiveView();
  }
});
measureButton.addEventListener("click", calculateMeasurement);
codeInput.addEventListener("input", scheduleCodeReview);
[cameraHeight, cameraTilt, cameraFov].forEach((input) => {
  input.addEventListener("change", calculateMeasurement);
});
zoomInput.addEventListener("input", () => {
  updateControlLabels();
  scheduleProcessing();
});
gammaInput.addEventListener("input", () => {
  updateControlLabels();
  scheduleProcessing();
});
[xInput, yInput].forEach((input) => {
  input.addEventListener("input", updateFocusMarker);
  input.addEventListener("change", () => {
    scheduleProcessing();
    void calculateMeasurement();
  });
});

focusPicker.addEventListener("click", (event) => {
  if (!sourceBlob) return;
  const frame = sourceFrame.getBoundingClientRect();
  const scale = Math.min(
    frame.width / sourceImage.naturalWidth,
    frame.height / sourceImage.naturalHeight,
  );
  const renderedWidth = sourceImage.naturalWidth * scale;
  const renderedHeight = sourceImage.naturalHeight * scale;
  const imageLeft = (frame.width - renderedWidth) / 2;
  const imageTop = (frame.height - renderedHeight) / 2;
  const localX = event.clientX - frame.left - imageLeft;
  const localY = event.clientY - frame.top - imageTop;
  if (localX < 0 || localY < 0 || localX > renderedWidth || localY > renderedHeight) return;

  updateCenterInputs(
    Math.min(sourceImage.naturalWidth - 1, Math.floor((localX / renderedWidth) * sourceImage.naturalWidth)),
    Math.min(sourceImage.naturalHeight - 1, Math.floor((localY / renderedHeight) * sourceImage.naturalHeight)),
  );
  scheduleProcessing();
  void calculateMeasurement();
});

window.addEventListener("resize", updateFocusMarker);

async function initialize() {
  updateControlLabels();
  try {
    const healthResponse = await fetch("/health");
    if (!healthResponse.ok) throw new Error(`HTTP ${healthResponse.status}`);
    setServiceStatus(true, "Servicio conectado");
  } catch {
    setServiceStatus(false, "Servicio desconectado");
    setError("Inicia la API para usar la web: python -m uvicorn api:app --reload");
    return;
  }

  try {
    const response = await fetch("/api/v1/config");
    if (!response.ok) throw new Error(await readApiError(response));
    appConfig = await response.json();
    zoomInput.min = String(appConfig.processing.zoom.min);
    zoomInput.max = String(appConfig.processing.zoom.max);
    zoomInput.step = String(appConfig.processing.zoom.step);
    zoomInput.value = String(appConfig.processing.zoom.default);
    gammaInput.min = String(appConfig.processing.gamma.min);
    gammaInput.max = String(appConfig.processing.gamma.max);
    gammaInput.step = String(appConfig.processing.gamma.step);
    gammaInput.value = String(appConfig.processing.gamma.default);
    fileInput.accept = appConfig.upload.content_types.join(",");
    codeInput.maxLength = appConfig.assistants.max_source_chars;
    const maxMegabytes = appConfig.upload.max_bytes / (1024 * 1024);
    uploadHelp.textContent = `${appConfig.upload.content_types.map((type) => type.replace("image/", "").toUpperCase()).join(", ")} · máximo ${maxMegabytes.toLocaleString("es-CL")} MB`;
    cameraHeight.value = String(appConfig.measurement.default_camera_height_m);
    cameraTilt.value = String(appConfig.measurement.default_tilt_deg);
    cameraFov.value = String(appConfig.measurement.default_vertical_fov_deg);
    liveButton.disabled = !appConfig.live_view.enabled;
    updateControlLabels();
    if (appConfig.live_view.enabled) {
      startLiveView();
    } else {
      await loadDemo();
    }
  } catch (error) {
    setError(formatError(error, "No se pudo cargar la configuración del servicio."));
  }
}

initialize();
