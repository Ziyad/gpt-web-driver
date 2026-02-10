(() => {
  const CANNED_REPLIES = [
    "I'm a demo assistant running locally. How can I help you today?",
    "That's an interesting question! In this demo, I provide pre-written responses to validate the chat interface works correctly with the automation layer.",
    "Great point. The gpt-web-driver project uses browser automation to interact with chat interfaces like this one.",
    "I understand. Let me know if you'd like to test anything else with this demo chat interface.",
    "Thanks for trying this out! This dummy chat is designed to match the DOM structure that the observer expects.",
  ];

  const WELCOME_MESSAGE =
    "Hello! I'm the gpt-web-driver demo assistant. Type a message below to try the chat interface.";

  // Response delay in ms. Override via data-reply-delay attribute on
  // <script> tag or the global window.__GWD_REPLY_DELAY for tests.
  const REPLY_DELAY = (() => {
    const scriptEl = document.currentScript;
    const attr = scriptEl && scriptEl.getAttribute("data-reply-delay");
    if (attr) return parseInt(attr, 10) || 300;
    if (typeof window.__GWD_REPLY_DELAY === "number") return window.__GWD_REPLY_DELAY;
    return 300;
  })();

  let messageCount = 0;
  let replyCount = 0;
  let isWaiting = false;

  const chatMessages = document.getElementById("chat-messages");
  const textarea = document.getElementById("prompt-textarea");
  const sendBtn = document.getElementById("send-btn");

  function createMessageNode(role, text) {
    const id = `msg-${Date.now()}-${messageCount}`;
    messageCount++;

    // Outer wrapper with data attributes (matches observer.py selectors)
    const row = document.createElement("div");
    row.className = `message-row ${role}`;
    row.setAttribute("data-message-author-role", role);
    row.setAttribute("data-message-id", id);

    // Avatar
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = role === "user" ? "U" : "A";

    // Bubble with content
    const bubble = document.createElement("div");
    bubble.className = "bubble";

    // Content node matching observer.py's content_selector
    const content = document.createElement("div");
    content.className = "whitespace-pre-wrap";
    content.textContent = text;

    bubble.appendChild(content);
    row.appendChild(avatar);
    row.appendChild(bubble);

    return row;
  }

  function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function sendMessage() {
    const text = textarea.value.trim();
    if (!text || isWaiting) return;

    // Append user message
    const userNode = createMessageNode("user", text);
    chatMessages.appendChild(userNode);
    scrollToBottom();

    // Clear input
    textarea.value = "";
    textarea.style.height = "auto";
    isWaiting = true;
    sendBtn.disabled = true;

    // Generate dummy assistant reply after configured delay
    const replyIndex = replyCount % CANNED_REPLIES.length;
    replyCount++;
    const replyText = CANNED_REPLIES[replyIndex];

    setTimeout(() => {
      const assistantNode = createMessageNode("assistant", replyText);
      chatMessages.appendChild(assistantNode);
      scrollToBottom();
      isWaiting = false;
      sendBtn.disabled = false;
      textarea.focus();
    }, REPLY_DELAY);
  }

  // Send on Enter (without Shift)
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Send on button click
  sendBtn.addEventListener("click", () => {
    sendMessage();
  });

  // Auto-resize textarea
  textarea.addEventListener("input", () => {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 150) + "px";
  });

  // Show welcome message on load
  const welcomeNode = createMessageNode("assistant", WELCOME_MESSAGE);
  chatMessages.appendChild(welcomeNode);
  scrollToBottom();

  // Focus textarea on desktop (skip on touch devices to avoid opening keyboard)
  if (!("ontouchstart" in window)) {
    textarea.focus();
  }
})();
