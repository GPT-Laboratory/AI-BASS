/* chat.js — full client script with robust WebSocket + auth handling */

let selectedPhone = "";
let authToken = null;
let ws = null;
let bound = false;
let sending = false; // debounce
let pendingSources = null; // Store sources for the last message
let sourcesMap = {}; // Map of reference_id -> source object for citation replacement
let isLoadingHistory = false; // Prevent multiple simultaneous history loads
let allHistoryLoaded = false; // Track if we've loaded all available history
let currentSkip = 0; // Track pagination offset
let isAdmin = false; // Track if current user is admin
let loadedMessageIds = new Set(); // Track loaded message IDs to prevent duplicates
let scrollDebounceTimer = null; // Debounce timer for scroll events
let historyDisabled = false; // Flag to prevent history loading after manual clear
let placeholderTimers = []; // Track all placeholder update timers
let sourceObjectStore = {}; // Global store for source objects indexed by unique keys

// WebSocket connection/heartbeat state
let shouldReconnect = true;
let reconnectAttempts = 0;
let reconnectTimer = null;
let heartbeatTimer = null;
let lastPongAt = 0;

// Auth watcher
let authWatchTimer = null;

/* ===================== AUTH HELPERS ===================== */

function parseJwt(token) {
  try {
    const [, payload] = token.split(".");
    return JSON.parse(atob(payload));
  } catch {
    return null;
  }
}

function tokenExpMs(token) {
  const p = parseJwt(token);
  return p && typeof p.exp === "number" ? p.exp * 1000 : 0;
}

function isAuthenticated() {
  const token = localStorage.getItem("chat_auth_token");
  if (!token) return false;
  const payload = parseJwt(token);
  if (!payload) return false;
  isAdmin = payload.role === "admin";
  return tokenExpMs(token) > Date.now();
}

function startAuthWatcher() {
  stopAuthWatcher();
  authWatchTimer = setInterval(() => {
    const token = localStorage.getItem("chat_auth_token");
    if (!token || tokenExpMs(token) <= Date.now()) {
      logout();
    }
  }, 3000);
}

function stopAuthWatcher() {
  if (authWatchTimer) {
    clearInterval(authWatchTimer);
    authWatchTimer = null;
  }
}

/* ===================== SETTINGS / PROMPTS ===================== */

async function loadPredefinedPrompts() {
  const res = await fetch("/settings", { headers: { Authorization: `Bearer ${authToken}` } });
  if (!res.ok) {
    if (res.status === 401) return logout();
    console.warn("Failed to load settings");
    return;
  }
  const data = await res.json();
  const prompts = normalizePredefined(data?.predefined_prompts);
  renderPredefinedPromptButtons(prompts);
}

function normalizePredefined(arr) {
  return Array.isArray(arr) ? arr.map((p) => (typeof p === "string" ? { name: p, text: "" } : { name: p?.name ?? "", text: p?.text ?? "" })) : [];
}

function renderPredefinedPromptButtons(prompts) {
  const wrap = document.getElementById("prompt-buttons");
  if (!wrap) return;
  wrap.innerHTML = "";

  if (!prompts || prompts.length === 0) return;

  prompts.forEach((p, i) => {
    const label = (p.name || `Prompt ${i + 1}`).trim();
    const text = (p.text || "").trim();
    if (!label && !text) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-outline-secondary btn-sm";
    btn.textContent = label || "Prompt";
    btn.addEventListener("click", () => {
      const msgEl = document.getElementById("message");
      if (!msgEl) return;
      msgEl.value = text || label;
      sendMessage();
    });
    wrap.appendChild(btn);
  });
}

/* ===================== UI SHOW/HIDE ===================== */

function showInterface() {
  if (isAuthenticated()) {
    authToken = localStorage.getItem("chat_auth_token");
    document.getElementById("login-container").style.display = "none";
    document.getElementById("chat-container").style.display = "block";

    const clearBtn = document.getElementById("clear-chat-btn");
    if (clearBtn) clearBtn.style.display = "none";

    startAuthWatcher();
    initializeChat();
  } else {
    document.getElementById("login-container").style.display = "block";
    document.getElementById("chat-container").style.display = "none";
    stopAuthWatcher();
  }
}

/* ===================== LOGIN / LOGOUT ===================== */

async function login(username, password) {
  const response = await fetch("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const ct = response.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await response.json() : { error: await response.text() };
  if (response.ok && data.token) {
    localStorage.setItem("chat_auth_token", data.token);
    authToken = data.token;
    showInterface();
    return true;
  }
  throw new Error(data.error || data.detail || "Login failed");
}

function logout() {
  shouldReconnect = false; // prevent reconnect loops
  stopAuthWatcher();

  localStorage.removeItem("chat_auth_token");
  authToken = null;

  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }

  if (ws) {
    try {
      ws.close();
    } catch {}
    ws = null;
  }

  showInterface();
}

// Placeholder message management
const placeholderMessages = [
  "...AI-BASS is starting to work...",
  "...AI-BASS is writing a response...",
  "...AI-BASS is searching for information...",
  "...AI-BASS is writing a response...",
  "...AI-BASS is making coffee...",
  "...AI-BASS is writing a response...",
  "...AI-BASS is thinking (what's taking so long)...",
];

function startPlaceholderCycle() {
  // Clear any existing timers
  clearPlaceholderTimers();

  // Add initial placeholder
  appendPlaceholderMessage(placeholderMessages[0]);

  // Schedule updates every 5 seconds
  placeholderMessages.forEach((message, index) => {
    if (index === 0) return; // Skip first message as it's already shown
    const timer = setTimeout(() => {
      updatePlaceholderMessage(message);
    }, index * 5000);
    placeholderTimers.push(timer);
  });
}

function clearPlaceholderTimers() {
  // Clear all scheduled timer updates
  placeholderTimers.forEach((timer) => clearTimeout(timer));
  placeholderTimers = [];
}

/* ===================== WEBSOCKET (ROBUST) ===================== */
function initializeChat() {
  if (ws) {
    try {
      ws.close();
    } catch {}
    ws = null;
  }
  shouldReconnect = true;
  reconnectAttempts = 0;

  // Bind event listeners ONLY ONCE before any WebSocket connections
  if (!bound) {
    const userSelect = document.getElementById("user-select");
    const sendBtn = document.getElementById("send-btn");
    const msgEl = document.getElementById("message");
    const chatForm = document.getElementById("chat-form");

    if (chatForm) {
      chatForm.setAttribute("novalidate", "novalidate");
      chatForm.addEventListener("submit", (e) => e.preventDefault());
    }

    // Use onclick to replace any existing handler, not addEventListener
    if (sendBtn) {
      sendBtn.onclick = () => sendMessage();
    }

    if (msgEl) {
      msgEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });
    }

    if (userSelect) {
      userSelect.addEventListener("change", (e) => loadUserDetails(e.target.value));
    }

    const chatlog = document.getElementById("chatlog");
    if (chatlog) {
      chatlog.addEventListener("scroll", handleChatScroll);
    }

    // Try reconnect when tab regains focus
    window.addEventListener("visibilitychange", () => {
      if (!document.hidden && (!ws || ws.readyState !== WebSocket.OPEN)) {
        connectWebSocket(true);
      }
    });

    bound = true;
  }

  // Connect WebSocket after binding is complete
  connectWebSocket();

  loadUsers();
  loadPredefinedPrompts();
}

function connectWebSocket(isResume = false) {
  if (!isAuthenticated()) {
    logout();
    return;
  }

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/ws?token=${encodeURIComponent(authToken)}`;

  try {
    ws = new WebSocket(url);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    reconnectAttempts = 0;
    lastPongAt = Date.now();

    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "ping", t: Date.now() }));
      if (Date.now() - lastPongAt > 45000) {
        try {
          ws.close();
        } catch {}
      }
    }, 20000);
  };

  ws.onclose = (ev) => {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }

    // Close due to auth issues (use server close codes if available)
    if (ev && (ev.code === 4001 || ev.code === 4401 || ev.code === 4403)) {
      logout();
      return;
    }

    if (shouldReconnect) scheduleReconnect();
  };

  ws.onerror = () => {
    // onclose handles reconnection
  };

  ws.onmessage = (ev) => {
    // JSON control messages first
    try {
      const parsed = JSON.parse(ev.data);

      if (parsed.type === "auth_error" || (parsed.type === "error" && (parsed.code === "UNAUTHORIZED" || parsed.code === "TOKEN_EXPIRED"))) {
        logout();
        return;
      }

      if (parsed.type === "pong") {
        lastPongAt = Date.now();
        return;
      }

      if (parsed.type === "debug_info") {
        console.group("🔍 LLM Request Debug Info");
        console.log("System Prompt:", parsed.data.system_prompt);
        console.log("Conversation History Count:", parsed.data.conversation_history_count);
        console.log("Current User Message:", parsed.data.current_user_message);
        console.log("Task Applied:", parsed.data.task_applied || "None");
        console.log("Task Template:", parsed.data.task_template || "None");
        console.log("RAG Context Length:", parsed.data.rag_context_length);
        console.log("Web Search Used:", parsed.data.web_search_used);

        // Log web search details if available
        if (parsed.data.web_search_used && parsed.data.web_search_query) {
          console.log("\n🔎 Web Search Details:");
          console.log("Search Query:", parsed.data.web_search_query);
          if (parsed.data.web_search_results && parsed.data.web_search_results.length > 0) {
            console.log(`Found ${parsed.data.web_search_results.length} results:`);
            console.table(
              parsed.data.web_search_results.map((r, i) => ({
                index: i + 1,
                title: r.title,
                snippet: r.snippet.substring(0, 80) + (r.snippet.length > 80 ? "..." : ""),
              }))
            );
            console.log("\nFull web search results (expandable):");
            console.log(parsed.data.web_search_results);
          }
        }

        console.log("\nFull Messages Array Sent to LLM:");
        console.table(
          parsed.data.messages_sent_to_llm.map((m, i) => ({
            index: i,
            role: m.role,
            content_preview: m.content.substring(0, 100) + (m.content.length > 100 ? "..." : ""),
            content_length: m.content.length,
          }))
        );
        console.log("\nComplete Messages (expandable):");
        console.log(parsed.data.messages_sent_to_llm);
        console.groupEnd();
        return; // Don't display debug info as a chat message
      } else if (parsed.type === "sources") {
        pendingSources = parsed.data;
        sourcesMap = {};
        parsed.data.forEach((source) => {
          sourcesMap[String(source.reference_id)] = source;
        });
        return;
      }
    } catch {
      // Not JSON or not a control message — treat as regular message
    }

    appendMessage("bot", ev.data);
  };
}

function scheduleReconnect() {
  if (!shouldReconnect) return;
  if (reconnectTimer) return;

  const base = 1000 * Math.pow(2, Math.min(reconnectAttempts, 5)); // 1s -> 32s
  const jitter = Math.floor(Math.random() * 500);
  const delay = Math.min(30000, base) + jitter;

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    reconnectAttempts += 1;
    connectWebSocket(true);
  }, delay);
}

/* ===================== SEND / HISTORY / USERS ===================== */
function sendMessage() {
  if (sending) return;
  if (!isAuthenticated()) {
    logout();
    return;
  }

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connectWebSocket(true);
    alert("WebSocket is not connected. Reconnecting...");
    return;
  }

  const msgEl = document.getElementById("message");
  const msg = (msgEl.value || "").trim();
  if (!selectedPhone) {
    alert("Select a user before sending.");
    return;
  }
  if (!msg) return;

  sending = true;

  // Reset sources for this request
  sourcesMap = {};
  pendingSources = null;

  ws.send(JSON.stringify({ message: msg, phone_number: selectedPhone, task: "" }));

  appendMessage("user", msg);
  msgEl.value = "";

  // Start placeholder message cycle
  startPlaceholderCycle();

  // release debounce after a tick
  setTimeout(() => {
    sending = false;
  }, 50);
}

async function loadUsers() {
  const res = await fetch("/users", { headers: { Authorization: `Bearer ${authToken}` } });
  if (!res.ok) {
    if (res.status === 401) return logout();
    throw new Error("Failed to load users");
  }
  const users = await res.json();
  const select = document.getElementById("user-select");
  const wrap = document.getElementById("user-select-container");
  const label = document.getElementById("user-select-label");

  if (Array.isArray(users) && users.length === 1) {
    selectedPhone = users[0].phone_number;
    if (select) select.style.display = "none";
    if (wrap) wrap.style.display = "none";
    if (label) label.style.display = "none";
    await loadUserDetails(selectedPhone);
    return;
  }

  if (wrap) wrap.style.display = "";
  if (label) label.style.display = "";
  if (select) {
    select.style.display = "";
    select.innerHTML = '<option value="">-- Select --</option>';
    (users || []).forEach((u) => {
      const opt = document.createElement("option");
      opt.value = u.phone_number;
      opt.innerText = `${u.first_name} ${u.last_name} (${u.phone_number})`;
      select.appendChild(opt);
    });
  }
}

async function loadUserDetails(phone) {
  const res = await fetch(`/user/${encodeURIComponent(phone)}`, { headers: { Authorization: `Bearer ${authToken}` } });
  if (!res.ok) {
    if (res.status === 401) return logout();
    throw new Error("Failed to load user details");
  }

  const data = await res.json();
  console.log(data);
  selectedPhone = phone;
  document.getElementById("chatlog").innerHTML = "";

  // Clear sources map when switching users
  sourcesMap = {};
  pendingSources = null;

  // Reset pagination state
  currentSkip = 0;
  allHistoryLoaded = false;
  loadedMessageIds.clear();
  historyDisabled = false;

  const info = document.getElementById("user-info");
  info.innerText = data.error ? "User not found." : `${data.first_name} ${data.last_name} – ${data.description || ""}`;

  // Show clear button for admin
  const clearBtn = document.getElementById("clear-chat-btn");
  if (clearBtn && isAdmin) {
    clearBtn.style.display = "block";
  }

  if (!historyDisabled) {
    await loadConversationHistory(phone, true);
  }
}

async function loadConversationHistory(phone, scrollToBottom = false) {
  if (isLoadingHistory || allHistoryLoaded || historyDisabled) {
    return;
  }

  isLoadingHistory = true;

  try {
    const res = await fetch(`/conversation/${encodeURIComponent(phone)}?skip=${currentSkip}&limit=10`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (!res.ok) {
      if (res.status === 401) return logout();
      console.warn("Failed to load conversation history");
      return;
    }

    const messages = await res.json();

    if (messages.length === 0) {
      allHistoryLoaded = true;
      return;
    }

    const chatlog = document.getElementById("chatlog");
    const scrollHeightBefore = chatlog.scrollHeight;
    const scrollTopBefore = chatlog.scrollTop;

    let newMessagesAdded = 0;
    const reversedMessages = [...messages].reverse();

    reversedMessages.forEach((msg) => {
      if (!msg.id) {
        prependMessage(msg.role, msg.content);
        newMessagesAdded++;
        return;
      }

      if (loadedMessageIds.has(msg.id)) {
        return;
      }

      loadedMessageIds.add(msg.id);
      prependMessage(msg.role, msg.content);
      newMessagesAdded++;
    });

    currentSkip += messages.length;

    if (scrollToBottom) {
      setTimeout(() => {
        chatlog.scrollTop = chatlog.scrollHeight;
      }, 0);
    } else {
      const scrollHeightAfter = chatlog.scrollHeight;
      const scrollDiff = scrollHeightAfter - scrollHeightBefore;
      chatlog.scrollTop = scrollTopBefore + scrollDiff;
    }

    if (messages.length < 10) {
      allHistoryLoaded = true;
    }
  } catch (error) {
    console.error("Error loading conversation history:", error);
  } finally {
    isLoadingHistory = false;
  }
}

function handleChatScroll() {
  const chatlog = document.getElementById("chatlog");
  if (!chatlog || !selectedPhone) return;

  if (scrollDebounceTimer) {
    clearTimeout(scrollDebounceTimer);
  }

  scrollDebounceTimer = setTimeout(() => {
    if (chatlog.scrollTop < 50 && !isLoadingHistory && !allHistoryLoaded) {
      loadConversationHistory(selectedPhone, false);
    }
  }, 100);
}

function clearChat() {
  const chatlog = document.getElementById("chatlog");
  if (chatlog) {
    chatlog.innerHTML = "";
    currentSkip = 0;
    allHistoryLoaded = false;
    loadedMessageIds.clear();
    sourcesMap = {};
    pendingSources = null;
    historyDisabled = true; // Disable history loading after manual clear
  }
}

/* ===================== BOOT ===================== */

window.onload = () => {
  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const username = document.getElementById("username").value;
      const password = document.getElementById("password").value;
      const err = document.getElementById("login-error");
      try {
        await login(username, password);
        if (err) err.style.display = "none";
      } catch (ex) {
        if (err) {
          err.textContent = ex.message;
          err.style.display = "block";
        }
      }
    });
  }
  showInterface();
};

/* ===================== RENDERING / SOURCES ===================== */

function formatMarkdown(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/_(.*?)_/g, "<em>$1</em>")
    .replace(/\[(.*?)\]\((https?:\/\/.*?)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\n/g, "<br>");
}

function getSourceIcon(source, refId, isLatestMessage = false) {
  const sourceType = source.type;
  const sourceTitle = source.title || source.source;

  // Create a unique store key for this source
  const storeKey = `source_${refId}_${Date.now()}_${Math.random()}`;
  sourceObjectStore[storeKey] = source;

  const clickHandler = isLatestMessage ? `onclick="showSourceContentFromStore('${storeKey}')" style="cursor: pointer;"` : "";

  if (sourceType === "website") {
    return `<img src="/static/globe.png" class="inline-source-icon" title="${escapeHtml(sourceTitle)}" alt="Web" onclick="window.open('${escapeHtml(
      source.source
    )}', '_blank')" style="cursor: pointer;">`;
  } else if (sourceType === "google_drive_file") {
    return `<img src="/static/gdrive.png" class="inline-source-icon" title="${escapeHtml(sourceTitle)}" alt="Google Drive" ${clickHandler}>`;
  } else if (sourceType === "onedrive_file") {
    return `<img src="/static/onedrive.png" class="inline-source-icon" title="${escapeHtml(sourceTitle)}" alt="OneDrive" ${clickHandler}>`;
  } else if (sourceType === "email") {
    return `<img src="/static/email.png" class="inline-source-icon" title="${escapeHtml(sourceTitle)}" alt="Email" ${clickHandler}>`;
  } else if (sourceType === "manual_upload_file") {
    return `<img src="/static/file.png" class="inline-source-icon" title="${escapeHtml(sourceTitle)}" alt="File" ${clickHandler}>`;
  } else if (sourceType === "ai_generated_memory") {
    return `<img src="/static/memory.png" class="inline-source-icon" title="Memory" alt="Memory" ${clickHandler}>`;
  } else {
    const formattedType = formatSourceType(sourceType);
    return `<img src="/static/metadata.png" class="inline-source-icon" title="${escapeHtml(formattedType)}" alt="${escapeHtml(formattedType)}" ${clickHandler}>`;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatSourceType(type) {
  // Transform type: replace underscores with spaces, then capitalize first letter of each word
  if (!type) return "";
  return type
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

function buildSourceTitle(source) {
  // Build title in format: "Type: Title" or just "Type" if title is empty
  const formattedType = formatSourceType(source.type);
  const title = source.title && source.title.trim() ? source.title.trim() : null;

  if (title) {
    return `${formattedType}: ${title}`;
  }

  return formattedType || "Source Content";
}

function showSourceContentFromStore(storeKey) {
  const source = sourceObjectStore[storeKey];
  if (!source) {
    console.error("Source not found in store:", storeKey);
    alert("Error: Source content not available");
    return;
  }
  showSourceContent(source);
}

function showSourceContentFromJson(jsonString) {
  try {
    const source = JSON.parse(jsonString);
    showSourceContent(source);
  } catch (e) {
    console.error("Failed to parse source JSON:", e);
    alert("Error displaying source content");
  }
}

function showSourceContent(source) {
  const title = buildSourceTitle(source);
  const content = source.content || "Content not available";

  // Get or create modal
  let modal = document.getElementById("source-content-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "source-content-modal";
    modal.className = "modal fade";
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-scrollable modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="source-content-modal-title">Source Content</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body" id="source-content-modal-body">
            <p>Loading...</p>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }

  document.getElementById("source-content-modal-title").textContent = title;
  document.getElementById("source-content-modal-body").innerHTML = `<pre style="white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(content)}</pre>`;

  const bsModal = new bootstrap.Modal(modal);
  bsModal.show();
}

function replaceCitationsWithIcons(text, isLatestMessage = false) {
  const hasSources = sourcesMap && Object.keys(sourcesMap).length > 0;

  if (!hasSources) {
    // No sources: strip citation markers
  }

  let result = text.replace(/(\[([A-Za-z0-9]+)\])+/g, (fullMatch) => {
    const citations = fullMatch.match(/\[([A-Za-z0-9]+)\]/g);
    if (!citations) return fullMatch;

    const icons = citations.map((citation) => {
      const refId = citation.slice(1, -1);
      const source = sourcesMap[refId];
      if (source) {
        return getSourceIcon(source, refId, isLatestMessage);
      }
      return "";
    });

    return icons.join("");
  });

  result = result.replace(/\s+([.,;:!?])/g, "$1");
  return result;
}

function appendPlaceholderMessage(text) {
  const chatlog = document.getElementById("chatlog");
  if (!chatlog) return;

  const row = document.createElement("div");
  row.className = "msg-row bot";
  row.dataset.role = "placeholder";
  row.id = "placeholder-message";

  const bubble = document.createElement("div");
  bubble.className = "msg bot placeholder-msg";
  bubble.innerHTML = `<span class="loader"></span><em>${text}</em>`;

  row.appendChild(bubble);
  chatlog.appendChild(row);
  chatlog.scrollTop = chatlog.scrollHeight;
}

function updatePlaceholderMessage(text) {
  const placeholder = document.getElementById("placeholder-message");
  if (!placeholder) return;

  const bubble = placeholder.querySelector(".msg");
  if (bubble) {
    bubble.innerHTML = `<span class="loader"></span><em>${text}</em>`;
  }
}

function removePlaceholderMessage() {
  const placeholder = document.getElementById("placeholder-message");
  if (placeholder) {
    placeholder.remove();
  }
  // Also clear any pending timers when removing placeholder
  clearPlaceholderTimers();
}

function appendMessage(role, rawText) {
  const chatlog = document.getElementById("chatlog");
  if (!chatlog) return;

  if (role === "bot") {
    removePlaceholderMessage();
  }

  const allRows = chatlog.querySelectorAll(".msg-row");
  allRows.forEach((row) => {
    row.dataset.isLatest = "false";
  });

  const row = document.createElement("div");
  row.className = `msg-row ${role === "bot" ? "bot" : "user"}`;
  row.dataset.role = role;
  row.dataset.isLatest = "true";

  const bubble = document.createElement("div");
  bubble.className = `msg ${role === "bot" ? "bot" : "user"}`;

  let formattedText = formatMarkdown(rawText);
  if (role === "bot") {
    formattedText = replaceCitationsWithIcons(formattedText, true);
  }

  bubble.innerHTML = formattedText;

  row.appendChild(bubble);
  chatlog.appendChild(row);
  chatlog.scrollTop = chatlog.scrollHeight;

  if (role === "bot" && pendingSources && pendingSources.length > 0) {
    attachSourcesToLastMessage(pendingSources);
    pendingSources = null;
  }
}

function prependMessage(role, rawText) {
  const chatlog = document.getElementById("chatlog");
  if (!chatlog) return;

  const row = document.createElement("div");
  row.className = `msg-row ${role === "bot" ? "bot" : role === "assistant" ? "bot" : "user"}`;
  row.dataset.role = role;
  row.dataset.isLatest = "false";

  const bubble = document.createElement("div");
  bubble.className = `msg ${role === "bot" || role === "assistant" ? "bot" : "user"}`;

  let formattedText = formatMarkdown(rawText);
  if (role === "bot" || role === "assistant") {
    formattedText = replaceCitationsWithIcons(formattedText, false);
  }

  bubble.innerHTML = formattedText;
  row.appendChild(bubble);

  chatlog.insertBefore(row, chatlog.firstChild);
}

function attachSourcesToLastMessage(sources) {
  const chatlog = document.getElementById("chatlog");
  if (!chatlog) return;

  const allRows = chatlog.querySelectorAll(".msg-row.bot:not([data-role='placeholder'])");
  if (allRows.length === 0) return;

  const lastBotRow = allRows[allRows.length - 1];
  const bubble = lastBotRow.querySelector(".msg.bot");
  if (!bubble) return;

  if (bubble.querySelector(".sources-container")) return;

  const isLatest = lastBotRow.dataset.isLatest === "true";

  const sourcesContainer = document.createElement("div");
  sourcesContainer.className = "sources-container";

  const label = document.createElement("span");
  label.className = "sources-label";
  label.innerText = "Sources read: ";
  sourcesContainer.appendChild(label);

  const iconsWrapper = document.createElement("span");
  iconsWrapper.className = "sources-icons";

  sources.forEach((source) => {
    const sourceType = source.type;
    const sourceTitle = source.title || source.source;
    const sourceContent = source.content || "Content not available";

    const img = document.createElement("img");
    img.className = "source-icon source-icon-img";
    img.title = sourceTitle;

    if (sourceType === "website") {
      img.src = "/static/globe.png";
      img.className = "source-icon source-icon-img";
      img.title = sourceTitle;
      img.alt = "Website";
      img.style.cursor = "pointer";
      img.onclick = () => window.open(source.source, "_blank");
    } else if (sourceType === "google_drive_file") {
      img.src = "/static/gdrive.png";
      img.alt = "Google Drive";
      if (isLatest) {
        img.style.cursor = "pointer";
        img.onclick = () => showSourceContent(source);
      }
    } else if (sourceType === "onedrive_file") {
      img.src = "/static/onedrive.png";
      img.alt = "OneDrive";
      if (isLatest) {
        img.style.cursor = "pointer";
        img.onclick = () => showSourceContent(source);
      }
    } else if (sourceType === "email") {
      img.src = "/static/email.png";
      img.className = "source-icon source-icon-img";
      img.title = sourceTitle;
      img.alt = "Email";
      if (isLatest) {
        img.style.cursor = "pointer";
        img.onclick = () => showSourceContent(source);
      }
    } else if (sourceType === "manual_upload_file") {
      img.src = "/static/file.png";
      img.className = "source-icon source-icon-img";
      img.title = sourceTitle;
      img.alt = "File";
      if (isLatest) {
        img.style.cursor = "pointer";
        img.onclick = () => showSourceContent(source);
      }
    } else if (sourceType === "ai_generated_memory") {
      img.src = "/static/memory.png";
      img.className = "source-icon source-icon-img";
      img.title = "Memory";
      img.alt = "Memory";
      if (isLatest) {
        img.style.cursor = "pointer";
        img.onclick = () => showSourceContent(source);
      }
    } else {
      img.src = "/static/metadata.png";
      img.className = "source-icon source-icon-img";
      const formattedType = formatSourceType(sourceType);
      img.title = formattedType;
      img.alt = formattedType;
      if (isLatest) {
        img.style.cursor = "pointer";
        img.onclick = () => showSourceContent(source);
      }
    }

    iconsWrapper.appendChild(img);
  });

  sourcesContainer.appendChild(iconsWrapper);
  bubble.appendChild(sourcesContainer);
}
