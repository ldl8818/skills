// SPDX-License-Identifier: Apache-2.0
// OpenCLI v2.0.2, clis/xiaohongshu/search.js: buildInSiteSearchJs.
// https://github.com/jackwener/opencli/blob/v2.0.2/clis/xiaohongshu/search.js
function buildInSiteSearchJs(query) {
    return `
      (async () => {
        const query = ${JSON.stringify(query)};
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const visible = (element) => {
          if (!element || element.closest('[aria-hidden="true"], [hidden], [inert]')) return false;
          const rect = element.getBoundingClientRect();
          if (rect.width <= 0 || rect.height <= 0) return false;
          for (let node = element; node; node = node.parentElement) {
            const style = element.ownerDocument.defaultView.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden' ||
                (style.opacity !== '' && Number(style.opacity) < 0.01)) return false;
          }
          return true;
        };
        const matches = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);
        const blocked = () => {
          const text = document.body?.innerText || document.body?.textContent || '';
          if (location.pathname.startsWith('/website-login/captcha') ||
              /请求太频繁|访问频次异常|安全限制|Requests too frequent|Scan with logged-in/i.test(text))
            return { status: 'security_block', detail: location.pathname };
          if (/登录后查看搜索结果/.test(text) || matches('#login-btn').length)
            return { status: 'auth', detail: 'login_wall' };
          return null;
        };
        let input = null;
        for (let attempt = 0; attempt < 50 && !input; attempt++) {
          const wall = blocked();
          if (wall) return wall;
          const inputs = matches('#search-input');
          if (inputs.length > 1) return { status: 'layout', detail: 'ambiguous_search_input' };
          input = inputs[0];
          if (!input) await sleep(100);
        }
        if (!(input instanceof HTMLInputElement) || input.disabled || input.readOnly)
          return { status: 'layout', detail: 'search_input_not_available' };
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        input.focus();
        setter.call(input, query);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await sleep(200);
        if (input.value !== query) return { status: 'layout', detail: 'search_input_not_filled' };
        const wall = blocked();
        if (wall) return wall;
        const buttons = matches('.search-icon');
        if (buttons.length !== 1) return { status: 'layout', detail: 'ambiguous_or_missing_search_button' };
        const button = buttons[0];
        if (button.disabled || button.getAttribute('aria-disabled') === 'true')
          return { status: 'layout', detail: 'search_button_disabled' };
        button.click();
        const deadline = Date.now() + ${SEARCH_NAVIGATION_SECONDS * 1000};
        while (Date.now() < deadline) {
          const wall = blocked();
          if (wall) return wall;
          const searchRendered = document.querySelector('.search-layout__top > .filter, .filter.ai-chat-filter, section.note-item, section:has(a[href*="/search_result/"])');
          const keyword = new URLSearchParams(location.search).get('keyword');
          if (location.pathname === '/search_result' && keyword === query &&
              (searchRendered || document.querySelector('.search-empty-wrapper'))) {
            return { status: 'ok', detail: location.pathname };
          }
          await sleep(100);
        }
        return { status: 'timeout', detail: location.pathname };
      })()
    `;
}
