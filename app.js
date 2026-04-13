(function main() {
  "use strict";

  const REQUIRED_FOLLOWING_PATH = "connections/followers_and_following/following.json";
  const OPTIONAL_RECENTLY_UNFOLLOWED_PATH = "connections/followers_and_following/recently_unfollowed_profiles.json";
  const FOLLOWERS_PATH_PATTERN = /^connections\/followers_and_following\/followers_(\d+)\.json$/;
  const PROFILE_STATUS_LABELS = {
    active: "활성 확인",
    rate_limited: "속도 제한",
    unavailable: "비활성·삭제 추정",
    unknown: "확인 불가",
  };
  const PROFILE_STATUS_BATCH_SIZE = 5;
  const PROFILE_STATUS_BATCH_DELAY_MS = 1500;
  const PROFILE_STATUS_CACHE_KEY = "instagram-unfollowers-profile-status-cache-v1";
  const PROFILE_STATUS_CACHE_TTLS_MS = {
    active: 24 * 60 * 60 * 1000,
    rate_limited: 10 * 60 * 1000,
    unavailable: 24 * 60 * 60 * 1000,
    unknown: 6 * 60 * 60 * 1000,
  };
  const TAB_COPY = {
    notFollowingBack: {
      description: "내가 팔로우 중이지만 나를 팔로우하지 않는 계정 목록입니다.",
      empty: "현재 언팔러가 없습니다.",
      emptyFiltered: "활성으로 확인된 현재 언팔러가 없습니다.",
    },
    followersOnly: {
      description: "나를 팔로우하지만 내가 맞팔하지 않은 계정 목록입니다.",
      empty: "맞팔하지 않은 팔로워가 없습니다.",
    },
    recentlyUnfollowed: {
      description: "내가 최근에 언팔한 계정 목록입니다.",
      empty: "최근 내가 언팔한 기록이 없습니다.",
    },
  };

  const state = {
    activeOnlyFilter: false,
    activeTab: "notFollowingBack",
    apiAvailable: null,
    fileName: "",
    profileChecks: new Map(),
    result: null,
    verificationError: "",
    verificationInProgress: false,
    verificationProgress: {
      done: 0,
      total: 0,
    },
  };

  const elements = {
    activeOnlyToggle: document.getElementById("active-only-toggle"),
    checkActiveButton: document.getElementById("check-active-button"),
    dropzone: document.getElementById("dropzone"),
    errorMessage: document.getElementById("error-message"),
    fileInput: document.getElementById("zip-input"),
    fileName: document.getElementById("file-name"),
    resultList: document.getElementById("result-list"),
    resultsCaption: document.getElementById("results-caption"),
    reviewNote: document.getElementById("review-note"),
    statusText: document.getElementById("status-text"),
    tabButtons: Array.from(document.querySelectorAll(".tab-button")),
    tabCounts: new Map(Array.from(document.querySelectorAll("[data-tab-count]")).map((node) => [node.dataset.tabCount, node])),
    tabDescription: document.getElementById("tab-description"),
    verificationMessage: document.getElementById("verification-message"),
    warningMessage: document.getElementById("warning-message"),
    summaryValues: new Map(Array.from(document.querySelectorAll("[data-summary]")).map((node) => [node.dataset.summary, node])),
  };
  const browserProfileStatusCache = loadProfileStatusCache();

  pruneProfileStatusCache();

  function normalizeUsername(username) {
    return String(username || "").trim().toLowerCase();
  }

  function pickEntry(baseEntry, nextEntry) {
    if (!baseEntry) {
      return { ...nextEntry };
    }

    const baseTime = Number.isFinite(baseEntry.timestamp) ? baseEntry.timestamp : -1;
    const nextTime = Number.isFinite(nextEntry.timestamp) ? nextEntry.timestamp : -1;

    if (nextTime > baseTime) {
      return {
        ...baseEntry,
        ...nextEntry,
        href: nextEntry.href || baseEntry.href,
        timestamp: nextEntry.timestamp ?? baseEntry.timestamp ?? null,
        username: nextEntry.username || baseEntry.username,
      };
    }

    return {
      ...baseEntry,
      href: baseEntry.href || nextEntry.href,
      timestamp: baseEntry.timestamp ?? nextEntry.timestamp ?? null,
      username: baseEntry.username || nextEntry.username,
    };
  }

  function dedupeEntries(entries) {
    const byUsername = new Map();

    entries.forEach((entry) => {
      if (!entry || !entry.normalizedUsername) {
        return;
      }

      const currentEntry = byUsername.get(entry.normalizedUsername);
      byUsername.set(entry.normalizedUsername, pickEntry(currentEntry, entry));
    });

    return Array.from(byUsername.values());
  }

  function sortEntries(entries) {
    return [...entries].sort((left, right) => {
      const leftTime = Number.isFinite(left.timestamp) ? left.timestamp : null;
      const rightTime = Number.isFinite(right.timestamp) ? right.timestamp : null;

      if (leftTime !== null && rightTime !== null && leftTime !== rightTime) {
        return rightTime - leftTime;
      }

      if (leftTime !== null && rightTime === null) {
        return -1;
      }

      if (leftTime === null && rightTime !== null) {
        return 1;
      }

      return left.username.localeCompare(right.username, "ko", { sensitivity: "base" });
    });
  }

  function createEntry(username, href, timestamp, source) {
    const normalizedUsername = normalizeUsername(username);

    if (!normalizedUsername) {
      return null;
    }

    return {
      href: href || null,
      normalizedUsername,
      source,
      timestamp: Number.isFinite(timestamp) ? timestamp : null,
      username: String(username).trim(),
    };
  }

  function parseJsonOrThrow(jsonText, source) {
    try {
      return JSON.parse(jsonText);
    } catch (error) {
      throw new Error(source + " JSON을 읽지 못했습니다.");
    }
  }

  function parseFollowersJson(jsonText, source) {
    const parsed = parseJsonOrThrow(jsonText, source);

    if (!Array.isArray(parsed)) {
      throw new Error(source + " 형식이 예상과 다릅니다.");
    }

    return parsed.flatMap((entry) => {
      const list = Array.isArray(entry.string_list_data) ? entry.string_list_data : [];

      return list
        .map((item) => createEntry(item.value, item.href, item.timestamp, source))
        .filter(Boolean);
    });
  }

  function parseFollowingJson(jsonText, source) {
    const parsed = parseJsonOrThrow(jsonText, source);
    const list = Array.isArray(parsed.relationships_following) ? parsed.relationships_following : null;

    if (!list) {
      throw new Error(source + " 형식이 예상과 다릅니다.");
    }

    return list
      .map((entry) => {
        const firstString = Array.isArray(entry.string_list_data) ? entry.string_list_data[0] || {} : {};
        return createEntry(entry.title, firstString.href, firstString.timestamp, source);
      })
      .filter(Boolean);
  }

  function parseRecentlyUnfollowedJson(jsonText, source) {
    const parsed = parseJsonOrThrow(jsonText, source);
    const list = Array.isArray(parsed.relationships_unfollowed_users) ? parsed.relationships_unfollowed_users : null;

    if (!list) {
      throw new Error(source + " 형식이 예상과 다릅니다.");
    }

    return list.flatMap((entry) => {
      const stringList = Array.isArray(entry.string_list_data) ? entry.string_list_data : [];

      return stringList
        .map((item) => createEntry(item.value, item.href, item.timestamp, source))
        .filter(Boolean);
    });
  }

  function compareEntries(parsedExport) {
    const followersByUsername = new Map(parsedExport.followers.map((entry) => [entry.normalizedUsername, entry]));
    const followingByUsername = new Map(parsedExport.following.map((entry) => [entry.normalizedUsername, entry]));
    const recentlyUnfollowed = sortEntries(parsedExport.recentlyUnfollowed);
    const notFollowingBack = [];
    const followersOnly = [];
    let mutualCount = 0;

    parsedExport.following.forEach((entry) => {
      if (followersByUsername.has(entry.normalizedUsername)) {
        mutualCount += 1;
      } else {
        notFollowingBack.push(entry);
      }
    });

    parsedExport.followers.forEach((entry) => {
      if (!followingByUsername.has(entry.normalizedUsername)) {
        followersOnly.push(entry);
      }
    });

    return {
      followersOnly: sortEntries(followersOnly),
      mutualCount,
      notFollowingBack: sortEntries(notFollowingBack),
      recentlyUnfollowed,
      summaryCounts: {
        followersCount: parsedExport.followers.length,
        followingCount: parsedExport.following.length,
        mutualCount,
        notFollowingBackCount: notFollowingBack.length,
        recentlyUnfollowedCount: recentlyUnfollowed.length,
      },
    };
  }

  function formatTimestamp(timestamp) {
    if (!Number.isFinite(timestamp)) {
      return "시간 정보 없음";
    }

    return new Intl.DateTimeFormat("ko-KR", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(timestamp * 1000));
  }

  function setStatus(message, fileName) {
    elements.statusText.textContent = message;
    elements.fileName.textContent = fileName || "";
  }

  function setMessage(element, message) {
    const hasMessage = Boolean(message);
    element.hidden = !hasMessage;
    element.textContent = message || "";
  }

  function getProfileStatusCacheTtlMs(status) {
    return PROFILE_STATUS_CACHE_TTLS_MS[status] || PROFILE_STATUS_CACHE_TTLS_MS.unknown;
  }

  function getProfileCheckReferenceTime(check) {
    if (!check) {
      return Number.NaN;
    }

    if (Number.isFinite(check.cacheSavedAt)) {
      return check.cacheSavedAt;
    }

    return Date.parse(check.checkedAt || "");
  }

  function isProfileCheckFresh(check, nowMs = Date.now()) {
    const referenceTime = getProfileCheckReferenceTime(check);

    if (!Number.isFinite(referenceTime)) {
      return false;
    }

    return nowMs - referenceTime <= getProfileStatusCacheTtlMs(check.status);
  }

  function loadProfileStatusCache() {
    try {
      const raw = window.localStorage.getItem(PROFILE_STATUS_CACHE_KEY);

      if (!raw) {
        return {};
      }

      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function persistProfileStatusCache() {
    try {
      window.localStorage.setItem(PROFILE_STATUS_CACHE_KEY, JSON.stringify(browserProfileStatusCache));
    } catch (error) {
      // Ignore storage failures so the app can continue in private browsing modes.
    }
  }

  function pruneProfileStatusCache(nowMs = Date.now()) {
    let changed = false;

    Object.keys(browserProfileStatusCache).forEach((username) => {
      const cachedCheck = browserProfileStatusCache[username];

      if (!cachedCheck || !isProfileCheckFresh(cachedCheck, nowMs)) {
        delete browserProfileStatusCache[username];
        changed = true;
      }
    });

    if (changed) {
      persistProfileStatusCache();
    }
  }

  function normalizeProfileCheckResult(item, options) {
    const cacheSavedAt = options && Number.isFinite(options.cacheSavedAt) ? options.cacheSavedAt : Date.now();
    const normalizedUsername = normalizeUsername(item && item.username);

    if (!normalizedUsername) {
      return null;
    }

    return {
      cacheSavedAt,
      cached: Boolean(options && options.cached),
      checkedAt: item && item.checkedAt ? item.checkedAt : new Date(cacheSavedAt).toISOString(),
      detail: (item && item.detail) || "",
      finalUrl: (item && item.finalUrl) || "",
      httpStatus: Number.isFinite(item && item.httpStatus) ? item.httpStatus : null,
      reason: (item && item.reason) || "",
      status: (item && item.status) || "unknown",
      username: normalizedUsername,
    };
  }

  function getCachedProfileStatus(username) {
    const normalizedUsername = normalizeUsername(username);

    if (!normalizedUsername) {
      return null;
    }

    pruneProfileStatusCache();
    const cachedCheck = browserProfileStatusCache[normalizedUsername];

    if (!cachedCheck) {
      return null;
    }

    if (!isProfileCheckFresh(cachedCheck)) {
      delete browserProfileStatusCache[normalizedUsername];
      persistProfileStatusCache();
      return null;
    }

    return normalizeProfileCheckResult(cachedCheck, {
      cacheSavedAt: cachedCheck.cacheSavedAt,
      cached: true,
    });
  }

  function rememberProfileStatus(item) {
    const normalizedCheck = normalizeProfileCheckResult(item, {
      cacheSavedAt: Date.now(),
      cached: Boolean(item && item.cached),
    });

    if (!normalizedCheck) {
      return null;
    }

    browserProfileStatusCache[normalizedCheck.username] = {
      cacheSavedAt: normalizedCheck.cacheSavedAt,
      checkedAt: normalizedCheck.checkedAt,
      detail: normalizedCheck.detail,
      finalUrl: normalizedCheck.finalUrl,
      httpStatus: normalizedCheck.httpStatus,
      reason: normalizedCheck.reason,
      status: normalizedCheck.status,
      username: normalizedCheck.username,
    };
    persistProfileStatusCache();
    return normalizedCheck;
  }

  function hydrateCachedProfileChecks(entries) {
    const nextChecks = new Map();

    entries.forEach((entry) => {
      const cachedCheck = getCachedProfileStatus(entry.normalizedUsername);

      if (cachedCheck) {
        nextChecks.set(entry.normalizedUsername, cachedCheck);
      }
    });

    state.profileChecks = nextChecks;
  }

  function getVerificationTargets() {
    if (!state.result) {
      return [];
    }

    return state.result.notFollowingBack
      .filter((entry) => !getProfileCheck(entry))
      .map((entry) => entry.normalizedUsername);
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function clearVerificationState() {
    state.activeOnlyFilter = false;
    state.profileChecks = new Map();
    state.verificationError = "";
    state.verificationInProgress = false;
    state.verificationProgress = {
      done: 0,
      total: 0,
    };
  }

  function getProfileCheck(entry) {
    const check = state.profileChecks.get(entry.normalizedUsername) || null;

    if (!check) {
      return null;
    }

    if (!isProfileCheckFresh(check)) {
      state.profileChecks.delete(entry.normalizedUsername);
      return null;
    }

    return check;
  }

  function getVerificationStats() {
    const baseEntries = state.result ? state.result.notFollowingBack : [];
    const stats = {
      active: 0,
      checked: 0,
      pending: 0,
      rateLimited: 0,
      total: baseEntries.length,
      unavailable: 0,
      unknown: 0,
    };

    baseEntries.forEach((entry) => {
      const check = getProfileCheck(entry);

      if (!check) {
        stats.pending += 1;
        return;
      }

      stats.checked += 1;

      if (check.status === "active") {
        stats.active += 1;
        return;
      }

      if (check.status === "unavailable") {
        stats.unavailable += 1;
        return;
      }

      if (check.status === "rate_limited") {
        stats.rateLimited += 1;
        return;
      }

      stats.unknown += 1;
    });

    return stats;
  }

  function getVisibleEntries(tabKey) {
    if (!state.result) {
      return [];
    }

    const baseEntries = state.result[tabKey];

    if (tabKey !== "notFollowingBack" || !state.activeOnlyFilter) {
      return baseEntries;
    }

    return baseEntries.filter((entry) => {
      const check = getProfileCheck(entry);
      return check && check.status === "active";
    });
  }

  function getEmptyMessage(tabKey) {
    if (tabKey === "notFollowingBack" && state.activeOnlyFilter) {
      return TAB_COPY[tabKey].emptyFiltered;
    }

    return TAB_COPY[tabKey].empty;
  }

  function renderEntries(entries, tabKey) {
    elements.resultList.innerHTML = "";

    if (!entries.length) {
      const emptyItem = document.createElement("li");
      emptyItem.className = "empty-state";
      emptyItem.textContent = getEmptyMessage(tabKey);
      elements.resultList.append(emptyItem);
      return;
    }

    const fragment = document.createDocumentFragment();

    entries.forEach((entry) => {
      const item = document.createElement("li");
      item.className = "result-item";

      const main = document.createElement("div");
      main.className = "result-main";

      const title = document.createElement("h3");
      title.textContent = entry.username;
      main.append(title);

      const meta = document.createElement("p");
      meta.textContent = formatTimestamp(entry.timestamp);
      main.append(meta);

      const check = getProfileCheck(entry);

      if (check) {
        const badges = document.createElement("div");
        badges.className = "status-badges";

        const statusBadge = document.createElement("span");
        statusBadge.className = "status-badge " + check.status.replace("_", "-");
        statusBadge.textContent = PROFILE_STATUS_LABELS[check.status] || "확인 불가";
        badges.append(statusBadge);

        if (check.reason) {
          const detailBadge = document.createElement("span");
          detailBadge.className = "status-badge";
          detailBadge.textContent = check.reason;
          badges.append(detailBadge);
        }

        if (check.cached) {
          const cacheBadge = document.createElement("span");
          cacheBadge.className = "status-badge";
          cacheBadge.textContent = "캐시";
          badges.append(cacheBadge);
        }

        main.append(badges);
      }

      item.append(main);

      if (entry.href) {
        const link = document.createElement("a");
        link.className = "result-link";
        link.href = entry.href;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = "프로필 열기";
        item.append(link);
      }

      fragment.append(item);
    });

    elements.resultList.append(fragment);
  }

  function renderPlaceholder(message) {
    elements.resultList.innerHTML = "";
    const placeholder = document.createElement("li");
    placeholder.className = "empty-state";
    placeholder.textContent = message;
    elements.resultList.append(placeholder);
  }

  function updateTabState() {
    elements.tabButtons.forEach((button) => {
      const isActive = button.dataset.tab === state.activeTab;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-selected", String(isActive));
    });

    const hasRecentData = Boolean(state.result && state.result.hasRecentData);
    const recentButton = elements.tabButtons.find((button) => button.dataset.tab === "recentlyUnfollowed");

    if (recentButton) {
      recentButton.disabled = !hasRecentData;

      if (!hasRecentData && state.activeTab === "recentlyUnfollowed") {
        state.activeTab = "notFollowingBack";
      }
    }
  }

  function updateSummary(summaryCounts) {
    elements.summaryValues.forEach((node, key) => {
      const value = summaryCounts && Number.isFinite(summaryCounts[key]) ? summaryCounts[key] : "-";
      node.textContent = value;
    });
  }

  function updateTabCounts(result) {
    const counts = result
      ? {
          followersOnly: result.followersOnly.length,
          notFollowingBack: result.notFollowingBack.length,
          recentlyUnfollowed: result.recentlyUnfollowed.length,
        }
      : {
          followersOnly: 0,
          notFollowingBack: 0,
          recentlyUnfollowed: 0,
        };

    elements.tabCounts.forEach((node, key) => {
      node.textContent = counts[key];
    });
  }

  function buildReviewNote() {
    if (!state.result) {
      return "ZIP만으로는 삭제/비활성화와 실제 언팔을 구분할 수 없어 프로필 상태를 다시 확인해야 합니다.";
    }

    if (state.activeTab !== "notFollowingBack") {
      return "활성 여부 재확인은 현재 언팔러 탭에서만 사용합니다.";
    }

    if (state.apiAvailable === null) {
      return "로컬 서버 연결 상태를 확인하는 중입니다.";
    }

    if (state.apiAvailable === false) {
      if (getVerificationStats().checked) {
        return "서버 연결 없이도 이전 확인 결과를 캐시에서 불러왔습니다.";
      }

      return "현재는 정적 파일 모드입니다. `python3 server.py`로 연 뒤 http://127.0.0.1:8000 에 접속하면 활성 여부를 다시 확인할 수 있습니다.";
    }

    if (state.verificationInProgress) {
      return "프로필 상태를 다시 확인하는 중입니다. " + state.verificationProgress.done + " / " + state.verificationProgress.total;
    }

    const stats = getVerificationStats();
    const pendingTargets = getVerificationTargets().length;

    if (!stats.checked) {
      return "버튼을 누르면 현재 언팔러 프로필을 조회해 활성 / 비활성·삭제 추정 / 확인 불가로 다시 분류합니다.";
    }

    if (!pendingTargets) {
      return "최근 확인 결과를 캐시에서 재사용했습니다. 활성 " + stats.active + "명, 비활성·삭제 추정 " + stats.unavailable + "명, 확인 불가 " + (stats.unknown + stats.rateLimited) + "명.";
    }

    return "최근 확인 결과: 활성 " + stats.active + "명, 비활성·삭제 추정 " + stats.unavailable + "명, 확인 불가 " + (stats.unknown + stats.rateLimited) + "명.";
  }

  function buildVerificationMessage() {
    if (!state.result || state.activeTab !== "notFollowingBack") {
      return "";
    }

    if (state.verificationError) {
      return state.verificationError;
    }

    const stats = getVerificationStats();

    if (!stats.checked) {
      return "";
    }

    if (stats.rateLimited) {
      return "인스타그램이 일부 요청을 제한했습니다. 잠시 후 다시 확인하면 결과가 더 채워질 수 있습니다.";
    }

    if (stats.unknown) {
      return "로그인 장벽이나 접근 제한 때문에 일부 계정은 확인 불가로 남았습니다.";
    }

    return "이 분류는 프로필 페이지 응답을 기준으로 한 재확인 결과입니다.";
  }

  function updateReviewControls() {
    const hasResult = Boolean(state.result);
    const onSupportedTab = hasResult && state.activeTab === "notFollowingBack";
    const stats = getVerificationStats();
    const verificationTargets = getVerificationTargets();
    const canCheck = onSupportedTab && state.apiAvailable === true && !state.verificationInProgress && verificationTargets.length > 0;
    const canFilter = onSupportedTab && stats.checked > 0 && !state.verificationInProgress;

    elements.checkActiveButton.disabled = !canCheck;
    elements.activeOnlyToggle.disabled = !canFilter;
    elements.activeOnlyToggle.checked = state.activeOnlyFilter;
    elements.reviewNote.textContent = buildReviewNote();
    setMessage(elements.verificationMessage, buildVerificationMessage());
  }

  function buildResultsCaption(visibleEntries) {
    if (!state.result) {
      return "파일을 올리면 목록이 열립니다.";
    }

    const baseCaption = state.fileName ? state.fileName + " 결과" : "결과";

    if (state.activeTab === "notFollowingBack" && state.activeOnlyFilter) {
      return baseCaption + " · 활성 확인 " + visibleEntries.length + "명 표시 / 원본 " + state.result.notFollowingBack.length + "명";
    }

    return baseCaption;
  }

  function renderResult() {
    updateTabState();
    updateTabCounts(state.result);
    updateSummary(state.result ? state.result.summaryCounts : null);
    updateReviewControls();

    if (!state.result) {
      elements.resultsCaption.textContent = "파일을 올리면 목록이 열립니다.";
      elements.tabDescription.textContent = TAB_COPY.notFollowingBack.description;
      renderPlaceholder("ZIP을 올리면 결과가 여기에 나타납니다.");
      return;
    }

    const visibleEntries = getVisibleEntries(state.activeTab);
    elements.resultsCaption.textContent = buildResultsCaption(visibleEntries);
    elements.tabDescription.textContent = TAB_COPY[state.activeTab].description;
    renderEntries(visibleEntries, state.activeTab);
  }

  function getSortedFollowerPaths(entries) {
    return Array.from(entries.keys())
      .map((path) => {
        const match = path.match(FOLLOWERS_PATH_PATTERN);
        return match ? { order: Number(match[1]), path } : null;
      })
      .filter(Boolean)
      .sort((left, right) => left.order - right.order)
      .map((item) => item.path);
  }

  async function parseInstagramExport(file) {
    const archiveEntries = await window.InstagramZipReader.parseZipArchive(file);
    const followerPaths = getSortedFollowerPaths(archiveEntries);
    const missingPaths = [];

    if (!followerPaths.length) {
      missingPaths.push("connections/followers_and_following/followers_*.json");
    }

    if (!archiveEntries.has(REQUIRED_FOLLOWING_PATH)) {
      missingPaths.push(REQUIRED_FOLLOWING_PATH);
    }

    if (missingPaths.length) {
      throw new Error("필수 파일을 찾지 못했습니다: " + missingPaths.join(", "));
    }

    const followersParts = await Promise.all(
      followerPaths.map(async (path) => parseFollowersJson(await archiveEntries.get(path).text(), path))
    );

    const following = parseFollowingJson(
      await archiveEntries.get(REQUIRED_FOLLOWING_PATH).text(),
      REQUIRED_FOLLOWING_PATH
    );

    let recentlyUnfollowed = [];
    let warning = "";
    let hasRecentData = false;

    if (archiveEntries.has(OPTIONAL_RECENTLY_UNFOLLOWED_PATH)) {
      recentlyUnfollowed = parseRecentlyUnfollowedJson(
        await archiveEntries.get(OPTIONAL_RECENTLY_UNFOLLOWED_PATH).text(),
        OPTIONAL_RECENTLY_UNFOLLOWED_PATH
      );
      hasRecentData = true;
    } else {
      warning = "recently_unfollowed_profiles.json 이 없어 최근 내가 언팔 탭은 비활성화됩니다.";
    }

    const parsedExport = {
      followers: dedupeEntries(followersParts.flat()),
      following: dedupeEntries(following),
      recentlyUnfollowed: dedupeEntries(recentlyUnfollowed),
    };

    return {
      comparison: compareEntries(parsedExport),
      hasRecentData,
      warning,
    };
  }

  async function handleFile(file) {
    if (!file) {
      return;
    }

    if (!file.name.toLowerCase().endsWith(".zip")) {
      state.fileName = file.name;
      setStatus("파일 형식을 확인해 주세요.", file.name);
      setMessage(elements.errorMessage, "ZIP 파일만 읽을 수 있습니다.");
      setMessage(elements.warningMessage, "");
      clearVerificationState();
      renderResult();
      return;
    }

    state.fileName = file.name;
    state.result = null;
    state.activeTab = "notFollowingBack";
    clearVerificationState();
    setMessage(elements.errorMessage, "");
    setMessage(elements.warningMessage, "");
    setStatus("파일을 읽는 중입니다.", file.name);
    renderResult();

    try {
      const parsed = await parseInstagramExport(file);
      state.result = {
        ...parsed.comparison,
        hasRecentData: parsed.hasRecentData,
      };
      hydrateCachedProfileChecks(state.result.notFollowingBack);

      setStatus("계산이 끝났습니다.", file.name);
      setMessage(elements.warningMessage, parsed.warning);
      renderResult();
    } catch (error) {
      state.result = null;
      clearVerificationState();
      updateSummary(null);
      updateTabCounts(null);
      renderResult();
      setStatus("파일을 읽지 못했습니다.", file.name);
      setMessage(elements.warningMessage, "");
      setMessage(elements.errorMessage, error instanceof Error ? error.message : "알 수 없는 오류가 생겼습니다.");
    }
  }

  function handleInputChange(event) {
    const [file] = event.target.files || [];
    handleFile(file);
  }

  function handleDragState(active) {
    elements.dropzone.classList.toggle("is-dragging", active);
  }

  function setupDropzone() {
    elements.fileInput.addEventListener("change", handleInputChange);

    ["dragenter", "dragover"].forEach((eventName) => {
      elements.dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        handleDragState(true);
      });
    });

    ["dragleave", "dragend"].forEach((eventName) => {
      elements.dropzone.addEventListener(eventName, () => handleDragState(false));
    });

    elements.dropzone.addEventListener("drop", (event) => {
      event.preventDefault();
      handleDragState(false);
      const [file] = event.dataTransfer.files || [];
      handleFile(file);
    });
  }

  function setupTabs() {
    elements.tabButtons.forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled || !state.result) {
          return;
        }

        state.activeTab = button.dataset.tab;
        renderResult();
      });
    });
  }

  function chunkEntries(entries, size) {
    const chunks = [];

    for (let index = 0; index < entries.length; index += size) {
      chunks.push(entries.slice(index, index + size));
    }

    return chunks;
  }

  async function fetchProfileStatusBatch(usernames) {
    const response = await fetch("/api/profile-status?usernames=" + encodeURIComponent(usernames.join(",")), {
      cache: "no-store",
    });

    if (!response.ok) {
      let detail = "";

      try {
        const payload = await response.json();
        detail = payload.error || "";
      } catch (error) {
        detail = "";
      }

      throw new Error(detail || "프로필 상태 확인 요청에 실패했습니다.");
    }

    return response.json();
  }

  async function runActiveCheck() {
    if (!state.result || state.activeTab !== "notFollowingBack") {
      return;
    }

    if (state.apiAvailable !== true) {
      state.verificationError = "활성 여부 재확인은 로컬 서버에서 열었을 때만 사용할 수 있습니다.";
      renderResult();
      return;
    }

    const usernames = getVerificationTargets();

    if (!usernames.length) {
      state.activeOnlyFilter = true;
      renderResult();
      return;
    }

    state.verificationError = "";
    state.verificationInProgress = true;
    state.verificationProgress = {
      done: 0,
      total: usernames.length,
    };
    renderResult();

    const nextChecks = new Map(state.profileChecks);

    try {
      const batches = chunkEntries(usernames, PROFILE_STATUS_BATCH_SIZE);

      for (let index = 0; index < batches.length; index += 1) {
        const batch = batches[index];
        const payload = await fetchProfileStatusBatch(batch);
        const results = Array.isArray(payload.results) ? payload.results : [];

        results.forEach((item) => {
          const normalizedCheck = rememberProfileStatus(item);
          const normalizedUsername = normalizeUsername(normalizedCheck && normalizedCheck.username);

          if (!normalizedUsername) {
            return;
          }

          nextChecks.set(normalizedUsername, normalizedCheck);
        });

        state.profileChecks = nextChecks;
        state.verificationProgress = {
          done: Math.min(state.verificationProgress.done + batch.length, usernames.length),
          total: usernames.length,
        };
        renderResult();

        if (index < batches.length - 1) {
          await delay(PROFILE_STATUS_BATCH_DELAY_MS);
        }
      }

      state.activeOnlyFilter = true;
    } catch (error) {
      state.verificationError = error instanceof Error ? error.message : "프로필 상태를 확인하지 못했습니다.";
    } finally {
      state.verificationInProgress = false;
      renderResult();
    }
  }

  function setupReviewTools() {
    elements.checkActiveButton.addEventListener("click", () => {
      if (!elements.checkActiveButton.disabled) {
        runActiveCheck();
      }
    });

    elements.activeOnlyToggle.addEventListener("change", (event) => {
      state.activeOnlyFilter = event.target.checked;
      renderResult();
    });
  }

  async function detectApiAvailability() {
    if (!window.location.protocol.startsWith("http")) {
      state.apiAvailable = false;
      renderResult();
      return;
    }

    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      state.apiAvailable = response.ok;
    } catch (error) {
      state.apiAvailable = false;
    }

    renderResult();
  }

  setupDropzone();
  setupTabs();
  setupReviewTools();
  renderResult();
  detectApiAvailability();
})();
