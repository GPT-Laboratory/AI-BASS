<template>
  <div class="container-fluid mt-4">
    <div class="row">
      <div class="col-12">
        <h2>{{ $t("usage_statistics") }}</h2>

        <!-- Controls -->
        <div class="card mb-4">
          <div class="card-body">
            <div class="row mb-3">
              <!-- Time Range Selector -->
              <div class="col-md-3">
                <label class="form-label">{{ $t("time_range") }}</label>
                <select class="form-select" v-model="selectedTimeRange" @change="fetchData">
                  <option value="24h">{{ $t("last_24_hours") }}</option>
                  <option value="7d">{{ $t("last_7_days") }}</option>
                  <option value="2w">{{ $t("last_2_weeks") }}</option>
                  <option value="1m">{{ $t("last_month") }}</option>
                  <option value="2m">{{ $t("last_2_months") }}</option>
                  <option value="3m">{{ $t("last_3_months") }}</option>
                  <option value="6m">{{ $t("last_6_months") }}</option>
                  <option value="all">{{ $t("all_time") }}</option>
                </select>
              </div>

              <!-- Cumulative Toggle -->
              <div class="col-md-3">
                <label class="form-label">{{ $t("display_mode") }}</label>
                <select class="form-select" v-model="isCumulative" @change="updateChart">
                  <option :value="false">{{ $t("non_cumulative") }}</option>
                  <option :value="true">{{ $t("cumulative") }}</option>
                </select>
              </div>

              <!-- Refresh Button -->
              <div class="col-md-3 d-flex align-items-end">
                <button class="btn btn-primary w-100" @click="fetchData" :disabled="loading">
                  <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
                  {{ $t("refresh") }}
                </button>
              </div>

              <!-- Clear Filters Button -->
              <div class="col-md-3 d-flex align-items-end">
                <button class="btn btn-secondary w-100" @click="clearFilters" :disabled="loading || (!selectedUserId && !selectedCompanyId && !selectedEnvironment)">
                  {{ $t("clear_filters") }}
                </button>
              </div>
            </div>
            <div class="row">

             <!-- Download Raw Logs Button -->
              <div class="col-md-4">
                <button class="btn btn-outline-info w-100" @click="downloadLogs" :disabled="loading || downloadingLogs">
                  {{ $t("download_logs") }}
                </button>
              </div>

              <!-- Download Token Logs Button -->
              <div class="col-md-4">
                <button class="btn btn-outline-primary w-100" @click="downloadTokenLogs" :disabled="loading || !rawData.length">
                  {{ $t("download_token_logs") }}
                </button>
              </div>

              <!-- Download Classifications Button -->
              <div class="col-md-4">
                <button class="btn btn-outline-secondary w-100" @click="downloadClassifications" :disabled="loading || !hasClassifications">
                  {{ $t("download_classifications") }}
                </button>
              </div>

            </div>
            <br>
            <div class="row">
              <!-- Environment Filter -->
              <div class="col-md-4">
                <label class="form-label">{{ $t("filter_by_environment") }}</label>
                <select class="form-select" v-model="selectedEnvironment" @change="onFilterChange">
                  <option :value="null">{{ $t("all_environments") }}</option>
                  <option value="course">{{ $t("course") }}</option>
                  <option value="development">{{ $t("development") }}</option>
                  <option value="production">{{ $t("production") }}</option>
                </select>
              </div>

              <!-- Company Filter -->
              <div class="col-md-4">
                <label class="form-label">{{ $t("filter_by_company") }}</label>
                <select class="form-select" v-model="selectedCompanyId" @change="onFilterChange">
                  <option :value="null">{{ $t("all_companies") }}</option>
                  <option v-for="company in filteredCompanies" :key="company.id" :value="company.id">
                    {{ company.id }}
                  </option>
                </select>
              </div>

              <!-- User Filter -->
              <div class="col-md-4">
                <label class="form-label">{{ $t("filter_by_user") }}</label>
                <select class="form-select" v-model="selectedUserId" @change="onFilterChange">
                  <option :value="null">{{ $t("all_users") }}</option>
                  <option v-for="user in filteredUsers" :key="user.id" :value="user.id">
                    {{ user.name }}
                  </option>
                </select>
              </div>
            </div>
            <div class="row mb-3 mt-3">
              <div class="col-md-8">
                <label class="form-label">{{ $t("report_script") }}</label>
                <select class="form-select" v-model="selectedReportScriptId" :disabled="loading || runningReportScript || !reportScripts.length">
                  <option :value="null">{{ $t("select_report_script") }}</option>
                  <option v-for="script in reportScripts" :key="script.id" :value="script.id">
                    {{ script.name }}
                  </option>
                </select>
              </div>
              <div class="col-md-4 d-flex align-items-end">
                <button class="btn btn-outline-success w-100" @click="downloadReportScript" :disabled="loading || runningReportScript || !selectedReportScriptId">
                  <span v-if="runningReportScript" class="spinner-border spinner-border-sm me-2"></span>
                  {{ $t("run_report_script") }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Chart Container -->
        <div class="card mb-4">
          <div class="card-body">
            <canvas ref="chartCanvas"></canvas>
          </div>
        </div>

        <!-- Loading/Error States -->
        <div v-if="error" class="alert alert-danger mt-3">
          {{ error }}
        </div>

        <!-- Summary Stats -->
        <div class="row mt-4" v-if="!loading && stats">
          <!-- Token Stats -->
          <div class="col">
            <div class="card stat-card">
              <div class="card-body">
                <h5 class="card-title">{{ $t("prompt_tokens") }}</h5>
                <p class="card-text display-6">{{ stats.promptTokens.toLocaleString() }}</p>
              </div>
            </div>
          </div>
          <div class="col">
            <div class="card stat-card">
              <div class="card-body">
                <h5 class="card-title">{{ $t("completion_tokens") }}</h5>
                <p class="card-text display-6">{{ stats.completionTokens.toLocaleString() }}</p>
              </div>
            </div>
          </div>
          <div class="col">
            <div class="card stat-card">
              <div class="card-body">
                <h5 class="card-title">{{ $t("cached_tokens") }}</h5>
                <p class="card-text display-6">{{ stats.cachedTokens.toLocaleString() }}</p>
              </div>
            </div>
          </div>
          <div class="col">
            <div class="card stat-card bg-primary text-white">
              <div class="card-body">
                <h5 class="card-title">{{ $t("total_tokens") }}</h5>
                <p class="card-text display-6">{{ stats.totalTokens.toLocaleString() }}</p>
              </div>
            </div>
          </div>
          <div class="col">
            <div class="card stat-card bg-success text-white">
              <div class="card-body">
                <h5 class="card-title">{{ $t("success_rate") }}</h5>
                <p class="card-text display-6">{{ successRate }}%</p>
                <p class="card-text small">{{ stats.successfulRequests }}/{{ stats.totalRequests }} {{ $t("requests") }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Classification Charts -->
        <div class="row mt-4" v-show="!loading && classifications && hasClassifications">
          <div class="col-12">
            <h3 class="mb-4">{{ $t("classification_statistics") }}</h3>
          </div>

          <!-- Prompt Type Chart -->
          <div class="col-xxl-3 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("prompt_type_distribution") }}</h5>
                <canvas ref="promptTypePieChart"></canvas>
              </div>
            </div>
          </div>

          <!-- Response Type Chart -->
          <div class="col-xxl-3 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("response_type_distribution") }}</h5>
                <canvas ref="responseTypePieChart"></canvas>
              </div>
            </div>
          </div>

          <!-- Tone Chart -->
          <div class="col-xxl-3 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("tone_distribution") }}</h5>
                <canvas ref="tonePieChart"></canvas>
              </div>
            </div>
          </div>

          <!-- Source Chart -->
          <div class="col-xxl-3 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("source_distribution") }}</h5>
                <canvas ref="sourcePieChart"></canvas>
              </div>
            </div>
          </div>
        </div>

        <!-- Additional Analytics -->
        <div class="row mt-4" v-if="!loading">
          <!-- Sankey: prompt -> response -> RAG class -->
          <div class="col-12 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("sankey_prompt_response_rag") }}</h5>
                <div v-if="sankeyLinks.length === 0" class="text-center text-muted">{{ $t("no_data") }}</div>
                <svg v-else :width="sankeyWidth" :height="sankeyHeight" ref="sankeySvg" class="w-100" :style="{ minHeight: `${sankeyHeight}px` }"></svg>
              </div>
            </div>
          </div>

          <!-- Radar: prompt / RAG class axes from settings -->
          <div class="col-12 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("prompt_rag_radar") }}</h5>
                <div v-if="!radarHasData" class="text-center text-muted">{{ radarDebug || $t("no_data") }}</div>
                <canvas ref="radarChart" v-show="radarHasData" class="radar-canvas w-100"></canvas>
              </div>
            </div>
          </div>

          <!-- Time horizon distribution -->
          <div class="col-12 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("time_horizon_distribution") }}</h5>
                <canvas ref="timeHorizonChart"></canvas>
              </div>
            </div>
          </div>

          <!-- RAG Class mass distribution -->
          <div class="col-xxl-4 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("rag_class_mass_distribution") }}</h5>
                <canvas ref="classMassChart"></canvas>
              </div>
            </div>
          </div>

          <!-- RAG Class usage (count) -->
          <div class="col-xxl-4 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("rag_class_usage_distribution") }}</h5>
                <canvas ref="classUsageChart"></canvas>
              </div>
            </div>
          </div>

          <!-- Metadata Distribution -->
          <div class="col-xxl-4 col-xl-12 col-md-12 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("metadata_distribution") }}</h5>
                <canvas ref="metadataChart"></canvas>
              </div>
            </div>
          </div>

          <!-- Activity Over Time -->
          <div class="col-xxl-4 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("activity_over_time") }}</h5>
                <canvas ref="activityChart"></canvas>
              </div>
            </div>
          </div>

          <!-- Prompt Length Distribution -->
          <div class="col-xxl-4 col-xl-6 col-md-6 mb-4">
            <div class="card classification-chart-card">
              <div class="card-body">
                <h5 class="card-title text-center mb-3">{{ $t("prompt_length_distribution") }}</h5>
                <canvas ref="promptLengthChart"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from "vue";
import { useStore } from "vuex";
import { useI18n } from "vue-i18n";
import { Chart, registerables } from "chart.js";
import ChartDataLabels from "chartjs-plugin-datalabels";
import {
  fetchTokenUsage,
  fetchLogEntries,
  fetchMetadataStats,
  fetchMetadataClassMass,
  fetchRagClassUsage,
  fetchTurnClassifications,
  fetchSettings,
  fetchReportScripts,
  runReportScript,
} from "../services/adminServices";

Chart.register(...registerables);

const { t } = useI18n();
const store = useStore();

const chartCanvas = ref(null);
const promptTypePieChart = ref(null);
const responseTypePieChart = ref(null);
const tonePieChart = ref(null);
const sourcePieChart = ref(null);
const metadataChart = ref(null);
const classMassChart = ref(null);
const classUsageChart = ref(null);
const activityChart = ref(null);
const promptLengthChart = ref(null);
const selectedTimeRange = ref("7d");
const isCumulative = ref(false);
const loading = ref(false);
const error = ref(null);
const rawData = ref([]);
const logEntries = ref([]);
const stats = ref(null);
const classifications = ref(null);
const dateRangeInfo = ref(null); // Store actual date range from backend
const companies = ref([]);
const users = ref([]);
const selectedEnvironment = ref(null);
const selectedCompanyId = ref(null);
const selectedUserId = ref(null);
// Quick lookup for company environments so we can infer env for logs that lack metrics.company_env
const companyEnvById = computed(() => {
  const map = {};
  (companies.value || []).forEach((c) => {
    if (c?.id) {
      map[c.id] = c.environment || "development";
    }
  });
  return map;
});
const downloadingLogs = ref(false);
const reportScripts = ref([]);
const selectedReportScriptId = ref(null);
const runningReportScript = ref(false);
const metadataStats = ref(null);
const metadataClassMass = ref(null);
const ragClassUsage = ref(null);
const turnClassifications = ref([]);
const settingsData = ref(null);
const radarAxes = ref([]);
let chartInstance = null;
let promptTypePieChartInstance = null;
let responseTypePieChartInstance = null;
let tonePieChartInstance = null;
let sourcePieChartInstance = null;
let metadataChartInstance = null;
let classMassChartInstance = null;
let classUsageChartInstance = null;
let activityChartInstance = null;
let promptLengthChartInstance = null;
const sankeySvg = ref(null);
const sankeyWidth = ref(1100);
const sankeyHeight = ref(520);
const sankeyLinks = ref([]);
const sankeyNodes = ref([]);
const radarChart = ref(null);
let radarChartInstance = null;
const radarHasData = ref(false);
const radarDebug = ref("");
const timeHorizonChart = ref(null);
let timeHorizonChartInstance = null;

// Computed success rate
const successRate = computed(() => {
  if (!stats.value || stats.value.totalRequests === 0) return 0;
  return ((stats.value.successfulRequests / stats.value.totalRequests) * 100).toFixed(1);
});

// Check if we have any classification data
const hasClassifications = computed(() => {
  if (!classifications.value) return false;
  return (
    (classifications.value.prompt_type && Object.keys(classifications.value.prompt_type).length > 0) ||
    (classifications.value.response_type && Object.keys(classifications.value.response_type).length > 0) ||
    (classifications.value.tone && Object.keys(classifications.value.tone).length > 0) ||
    (classifications.value.source && Object.keys(classifications.value.source).length > 0)
  );
});

// Filter companies based on selected environment
const filteredCompanies = computed(() => {
  if (!selectedEnvironment.value) {
    return companies.value;
  }
  return companies.value.filter((company) => company.environment === selectedEnvironment.value);
});

// Filter users based on selected environment and company
const filteredUsers = computed(() => {
  let filtered = users.value;

  // First filter by environment if selected
  if (selectedEnvironment.value) {
    const envCompanyIds = filteredCompanies.value.map((c) => c.id);
    filtered = filtered.filter((user) => envCompanyIds.includes(user.company_id));
  }

  // Then filter by company if selected
  if (selectedCompanyId.value) {
    filtered = filtered.filter((user) => user.company_id === selectedCompanyId.value);
  }

  return filtered;
});

const computeSankey = () => {
  const nodes = [];
  const nodeIndex = new Map();
  const addNode = (name, group) => {
    const key = `${group}:${name}`;
    if (!nodeIndex.has(key)) {
      nodeIndex.set(key, nodes.length);
      nodes.push({ name, group });
    }
    return nodeIndex.get(key);
  };

  const links = [];

  const promptCounts = {};
  const respCounts = {};
  const ragCounts = {};

  turnClassifications.value.forEach((turn) => {
    const p = turn.prompt_type || "unknown";
    const r = turn.response_type || "unknown";
    const ragList = Array.isArray(turn.rag_classes) && turn.rag_classes.length ? turn.rag_classes : [{ class: "unknown" }];
    promptCounts[p] = (promptCounts[p] || 0) + 1;
    respCounts[r] = (respCounts[r] || 0) + 1;
    ragList.forEach((rc) => {
      const c = rc.class || "unknown";
      ragCounts[c] = (ragCounts[c] || 0) + 1;
      // link prompt->response
      const pIdx = addNode(p, "prompt");
      const rIdx = addNode(r, "response");
      const ragIdx = addNode(c, "rag");

      const prKey = `${pIdx}-${rIdx}`;
      const rrKey = `${rIdx}-${ragIdx}`;

      const prLink = links.find((l) => l.source === pIdx && l.target === rIdx);
      if (prLink) {
        prLink.value += 1;
      } else {
        links.push({ source: pIdx, target: rIdx, value: 1 });
      }

      const rrLink = links.find((l) => l.source === rIdx && l.target === ragIdx);
      if (rrLink) {
        rrLink.value += 1;
      } else {
        links.push({ source: rIdx, target: ragIdx, value: 1 });
      }
    });
  });

  sankeyNodes.value = nodes;
  sankeyLinks.value = links;
  // Dynamically size height based on largest column
  const maxColumnCount = Math.max(
    nodes.filter((n) => n.group === "prompt").length,
    nodes.filter((n) => n.group === "response").length,
    nodes.filter((n) => n.group === "rag").length
  );
  const padding = 10;
  const nodeHeight = 52;
  const nodeMargin = 15;
  const calculatedHeight = padding * 2 + maxColumnCount * nodeHeight + (Math.max(0, maxColumnCount - 1) * nodeMargin);
  sankeyHeight.value = Math.max(calculatedHeight, 520); // keep a sensible minimum
};

// Build radar data from settings-defined axes
const computeRadarMetrics = () => {
  console.log("Radar compute start. Axes:", radarAxes.value?.length || 0, "turns:", turnClassifications.value?.length || 0);
  if (!radarAxes.value || !radarAxes.value.length) {
    radarDebug.value = "No radar axes configured in settings.";
    console.warn("Radar skipped: no axes");
    return null;
  }
  if (!turnClassifications.value.length) {
    radarDebug.value = "No turn classifications loaded for the selected window.";
    console.warn("Radar skipped: no turn classifications for current filters/time window.");
    return null;
  }

  const norm = (v) => (v || "").toString().toLowerCase().trim();
  const labels = [];
  const promptSeries = [];
  const ragSeries = [];
  const promptUniverse = new Set();
  const ragUniverse = new Set();

  turnClassifications.value.forEach((turn) => {
    if (turn?.prompt_type) promptUniverse.add(norm(turn.prompt_type));
    if (Array.isArray(turn?.rag_classes)) {
      turn.rag_classes.forEach((rc) => {
        const c = norm(rc.class || rc);
        if (c) ragUniverse.add(c);
      });
    }
  });
  console.log("Radar prompt universe:", Array.from(promptUniverse));
  console.log("Radar rag universe:", Array.from(ragUniverse));

  radarAxes.value.forEach((axis) => {
    const label = axis.name || axis.axis || axis.label || t("unknown");
    labels.push(label);

    const promptSet = (axis.prompt_classes || axis.prompt_types || axis.prompts || []).map(norm).filter(Boolean);
    const ragSet = (axis.rag_classes || axis.rag_document_classes || axis.rag || []).map(norm).filter(Boolean);

    let promptCount = 0;
    let ragCount = 0;

    turnClassifications.value.forEach((turn) => {
      const promptType = norm(turn.prompt_type);
      if (promptSet.length && promptSet.includes(promptType)) {
        promptCount += 1;
      }

      const ragList = Array.isArray(turn.rag_classes) ? turn.rag_classes : [];
      if (ragSet.length && ragList.some((rc) => ragSet.includes(norm(rc.class || rc)))) {
        ragCount += 1;
      }
    });

    promptSeries.push(promptCount);
    ragSeries.push(ragCount);
  });

  const hasValues = [...promptSeries, ...ragSeries].some((v) => v > 0);
  if (!hasValues) {
    radarDebug.value = "Radar has no matching data between axes and turns.";
    return null;
  }

  radarDebug.value = `Radar ready: ${radarAxes.value.length} axes, ${turnClassifications.value.length} turns.`;
  console.log("Radar metrics computed:", { labels, promptSeries, ragSeries });
  return { labels, promptSeries, ragSeries };
};

// Calculate time range
const getTimeRange = () => {
  const end = new Date();
  const start = new Date();

  switch (selectedTimeRange.value) {
    case "24h":
      start.setHours(start.getHours() - 24);
      break;
    case "7d":
      start.setDate(start.getDate() - 7);
      break;
    case "2w":
      start.setDate(start.getDate() - 14);
      break;
    case "1m":
      start.setMonth(start.getMonth() - 1);
      break;
    case "2m":
      start.setMonth(start.getMonth() - 2);
      break;
    case "3m":
      start.setMonth(start.getMonth() - 3);
      break;
    case "6m":
      start.setMonth(start.getMonth() - 6);
      break;
    case "all":
      start.setFullYear(2020, 0, 1); // Far past date
      break;
  }

  return { start, end };
};

const formatDateForFilename = (date) => {
  try {
    return date.toISOString().split("T")[0];
  } catch (e) {
    return "unknown";
  }
};

// Flatten nested objects into dot.notation keys to split metrics/classifications into columns
const flattenObject = (obj, prefix = "", result = {}) => {
  if (!obj || typeof obj !== "object") return result;

  Object.keys(obj).forEach((key) => {
    const value = obj[key];
    const newKey = prefix ? `${prefix}.${key}` : key;

    if (value && typeof value === "object" && !Array.isArray(value)) {
      flattenObject(value, newKey, result);
    } else {
      result[newKey] = value;
    }
  });

  return result;
};

// Map metadata source to human-friendly label
const formatMetadataSource = (source) => {
  const map = {
    google_drive: t("google_drive") || "Google Drive",
    onedrive: t("onedrive") || "OneDrive",
    email: t("email") || "Email",
    manual_upload: t("manual_upload") || "Manual Upload",
    manual_upload_file: t("manual_upload") || "Manual Upload",
    manual_file_upload: t("manual_upload") || "Manual Upload",
    metadata: t("metadata") || "Metadata",
    chat_service: t("chat_service") || "Chat service",
    manual: t("manual_upload") || "Manual Upload",
    unknown: t("unknown") || "Unknown",
  };
  return map[source] || source || t("unknown") || "Unknown";
};

// Download current raw data as CSV for the selected time window
const downloadTokenLogs = () => {
  if (!rawData.value || rawData.value.length === 0) return;

  // Use actual range for "all" if backend provided it
  const { start, end } = getTimeRange();
  const exportStart = selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_start ? new Date(dateRangeInfo.value.actual_start) : start;
  const exportEnd = selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_end ? new Date(dateRangeInfo.value.actual_end) : end;

  // Collect headers from all objects to keep every field
  const headers = Array.from(
    rawData.value.reduce((set, item) => {
      Object.keys(item || {}).forEach((key) => set.add(key));
      return set;
    }, new Set())
  );

  const escapeCsv = (value) => {
    if (value === null || value === undefined) return "";
    const stringValue = typeof value === "object" ? JSON.stringify(value) : String(value);
    return /[",\n]/.test(stringValue) ? `"${stringValue.replace(/"/g, '""')}"` : stringValue;
  };

  const csvRows = rawData.value.map((row) => headers.map((header) => escapeCsv(row?.[header])).join(","));
  const csvContent = [headers.join(","), ...csvRows].join("\n");

  const filename = `token-usage-${formatDateForFilename(exportStart)}-${formatDateForFilename(exportEnd)}.csv`;
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
};

// Download raw log_entries directly from the backend for the selected window/filters
const downloadLogs = async () => {
  if (downloadingLogs.value) return;

  downloadingLogs.value = true;
  try {
    const { start, end } = getTimeRange();
    const exportStart = selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_start ? new Date(dateRangeInfo.value.actual_start) : start;
    const exportEnd = selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_end ? new Date(dateRangeInfo.value.actual_end) : end;

    const token = store.state?.admin?.authToken || localStorage.getItem("authToken");
    const response = await fetchLogEntries(
      start.toISOString(),
      end.toISOString(),
      token,
      selectedUserId.value,
      selectedCompanyId.value,
      selectedEnvironment.value
    );

    const logs = response.data?.logs || response.data || [];
    if (!logs.length) {
      downloadingLogs.value = false;
      return;
    }

    // Flatten nested objects (e.g., metrics, classifications) into separate columns
    const flattenedLogs = logs.map((log) => flattenObject(log));

    // Build CSV from all fields present across flattened logs
    const headers = Array.from(
      flattenedLogs.reduce((set, item) => {
        Object.keys(item || {}).forEach((key) => set.add(key));
        return set;
      }, new Set())
    );

    const escapeCsv = (value) => {
      if (value === null || value === undefined) return "";
      const stringValue = typeof value === "object" ? JSON.stringify(value) : String(value);
      return /[",\n]/.test(stringValue) ? `"${stringValue.replace(/"/g, '""')}"` : stringValue;
    };

    const csvRows = flattenedLogs.map((row) => headers.map((header) => escapeCsv(row?.[header])).join(","));
    const csvContent = [headers.join(","), ...csvRows].join("\n");

    const filename = `logs-${formatDateForFilename(exportStart)}-${formatDateForFilename(exportEnd)}.csv`;
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    error.value = t("error_fetching_data") + ": " + (err.response?.data?.error || err.message);
    console.error("Error downloading logs:", err);
  } finally {
    downloadingLogs.value = false;
  }
};

// Download aggregated classifications as JSON (prompt/response/tone/source counts)
const downloadClassifications = () => {
  if (!classifications.value || !hasClassifications.value) return;

  const { start, end } = getTimeRange();
  const exportStart = selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_start ? new Date(dateRangeInfo.value.actual_start) : start;
  const exportEnd = selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_end ? new Date(dateRangeInfo.value.actual_end) : end;

  const rows = [];
  const addRows = (type, dataObj) => {
    if (!dataObj) return;
    Object.entries(dataObj).forEach(([label, count]) => {
      rows.push({ type, label, count });
    });
  };

  addRows("prompt_type", classifications.value.prompt_type);
  addRows("response_type", classifications.value.response_type);
  addRows("tone", classifications.value.tone);
  addRows("source", classifications.value.source);

  const headers = ["type", "label", "count"];
  const csvRows = rows.map((r) => headers.map((h) => (r[h] === null || r[h] === undefined ? "" : String(r[h]))).join(","));
  const csvContent = [headers.join(","), ...csvRows].join("\n");

  const filename = `token-usage-classifications-${formatDateForFilename(exportStart)}-${formatDateForFilename(exportEnd)}.csv`;
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
};

const getExportRange = () => {
  const { start, end } = getTimeRange();
  return {
    start: selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_start ? new Date(dateRangeInfo.value.actual_start) : start,
    end: selectedTimeRange.value === "all" && dateRangeInfo.value?.actual_end ? new Date(dateRangeInfo.value.actual_end) : end,
  };
};

const loadReportScripts = async () => {
  try {
    const token = store.state?.admin?.authToken || localStorage.getItem("authToken");
    const response = await fetchReportScripts(token);
    reportScripts.value = response.data?.scripts || [];
    if (!selectedReportScriptId.value && reportScripts.value.length) {
      selectedReportScriptId.value = reportScripts.value[0].id;
    }
  } catch (err) {
    console.error("Error fetching report scripts:", err);
  }
};

const downloadReportScript = async () => {
  if (!selectedReportScriptId.value || runningReportScript.value) return;

  runningReportScript.value = true;
  try {
    const token = store.state?.admin?.authToken || localStorage.getItem("authToken");
    const { start, end } = getExportRange();
    const response = await runReportScript(
      selectedReportScriptId.value,
      {
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        company_env: selectedEnvironment.value,
        company_id: selectedCompanyId.value,
        user_id: selectedUserId.value,
      },
      token
    );

    const blob = new Blob([
      response.data,
    ], {
      type: response.headers["content-type"] || "application/octet-stream",
    });

    let filename = `${selectedReportScriptId.value}.xlsx`;
    const disposition = response.headers["content-disposition"] || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    if (match?.[1]) {
      filename = match[1];
    }

    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    error.value = t("error_fetching_data") + ": " + (err.response?.data?.error || err.message);
    console.error("Error running report script:", err);
  } finally {
    runningReportScript.value = false;
  }
};

// Fetch data from API
const fetchData = async () => {
  loading.value = true;
  error.value = null;

  try {
    const { start, end } = getTimeRange();
    const token = store.state?.admin?.authToken || localStorage.getItem("authToken");
    const response = await fetchTokenUsage(start.toISOString(), end.toISOString(), token, selectedUserId.value, selectedCompanyId.value, selectedEnvironment.value);
    // Fetch logs without environment filtering; we'll filter client-side using company_env and company mapping
    const logsResponse = await fetchLogEntries(start.toISOString(), end.toISOString(), token, selectedUserId.value, selectedCompanyId.value, null);
    const metadataResponse = await fetchMetadataStats(start.toISOString(), end.toISOString(), token, selectedCompanyId.value);
    const classMassResponse = await fetchMetadataClassMass(start.toISOString(), end.toISOString(), token, selectedCompanyId.value);
    const ragClassUsageResponse = await fetchRagClassUsage(start.toISOString(), end.toISOString(), token, selectedCompanyId.value);
    const turnClassificationsResponse = await fetchTurnClassifications(start.toISOString(), end.toISOString(), token, selectedUserId.value, selectedCompanyId.value);
    const settingsResponse = await fetchSettings(token);
    console.log("metadata", metadataResponse.data);
    // Handle new response structure
    rawData.value = response.data.data || response.data; // Support both old and new format
    companies.value = response.data.companies || [];
    users.value = response.data.users || [];
    classifications.value = response.data.classifications || null;
    dateRangeInfo.value = response.data.date_range || null; // Store date range info
    logEntries.value = logsResponse.data?.logs || logsResponse.data || [];
    metadataStats.value = metadataResponse.data || null;
    metadataClassMass.value = classMassResponse.data || null;
    ragClassUsage.value = ragClassUsageResponse.data || null;
    turnClassifications.value = turnClassificationsResponse.data?.data || [];
    settingsData.value = settingsResponse.data || null;
    radarAxes.value = settingsData.value?.radar_axes || settingsData.value?.analytics?.radar_axes || [];
    console.log("Radar axes from settings:", radarAxes.value);
    console.log("Turn classifications fetched:", turnClassifications.value?.length || 0);

    console.log("Classifications received:", classifications.value);
    console.log("Date range info:", dateRangeInfo.value);

    calculateStats();

    try {
      updateChart();
    } catch (chartErr) {
      console.error("Error updating main chart:", chartErr);
    }

    // Wait for next tick to ensure DOM is updated before creating classification charts
    await nextTick();

    try {
      updateClassificationCharts();
    } catch (classErr) {
      console.error("Error updating classification charts:", classErr);
    }
    computeSankey();
    drawSankeyChart();

  } catch (err) {
    error.value = t("error_fetching_data") + ": " + (err.response?.data?.error || err.message);
    console.error("Error fetching token usage:", err);

    // Clear data on error to prevent stale state
    rawData.value = [];
    classifications.value = null;
    dateRangeInfo.value = null;
    logEntries.value = [];
    metadataStats.value = null;
    metadataClassMass.value = null;
    ragClassUsage.value = null;
    turnClassifications.value = [];
    settingsData.value = null;
    radarAxes.value = [];
    radarHasData.value = false;
    if (radarChartInstance) {
      try {
        radarChartInstance.destroy();
      } catch (e) {
        console.warn("Error destroying radar chart after error:", e);
      }
      radarChartInstance = null;
    }
  } finally {
    loading.value = false;
    // Ensure DOM has rendered charts area before creating charts
    await nextTick();
    try {
      updateMetadataChart();
    } catch (metaErr) {
      console.error("Error updating metadata chart:", metaErr);
    }
    try {
      updateClassMassChart();
      updateClassUsageChart();
    } catch (massErr) {
      console.error("Error updating class charts:", massErr);
    }
    try {
      updateClassMassChart();
    } catch (massErr) {
      console.error("Error updating class mass chart:", massErr);
    }
    try {
      updateActivityChart();
    } catch (activityErr) {
      console.error("Error updating activity chart:", activityErr);
    }
    try {
      updatePromptLengthChart();
    } catch (promptErr) {
      console.error("Error updating prompt length chart:", promptErr);
    }
    try {
      renderTimeHorizonChart();
    } catch (horizonErr) {
      console.error("Error updating time horizon chart:", horizonErr);
    }
    try {
      drawSankeyChart();
    } catch (sankeyErr) {
      console.error("Error updating sankey chart:", sankeyErr);
    }
    try {
      updateRadarChart();
    } catch (radarErr) {
      console.error("Error updating radar chart:", radarErr);
    }
  }
};

// Handle filter changes
const onFilterChange = () => {
  // If environment changed, clear company and user if they don't match
  if (selectedEnvironment.value) {
    const envCompanyIds = filteredCompanies.value.map((c) => c.id);

    // Clear company selection if it doesn't belong to selected environment
    if (selectedCompanyId.value && !envCompanyIds.includes(selectedCompanyId.value)) {
      selectedCompanyId.value = null;
    }

    // Clear user selection if they don't belong to companies in selected environment
    if (selectedUserId.value) {
      const selectedUser = users.value.find((u) => u.id === selectedUserId.value);
      if (selectedUser && !envCompanyIds.includes(selectedUser.company_id)) {
        selectedUserId.value = null;
      }
    }
  }

  // If company filter changed, clear user selection if user doesn't belong to selected company
  if (selectedCompanyId.value && selectedUserId.value) {
    const selectedUser = users.value.find((u) => u.id === selectedUserId.value);
    if (selectedUser && selectedUser.company_id !== selectedCompanyId.value) {
      selectedUserId.value = null;
    }
  }

  fetchData();
};


// Clear all filters
const clearFilters = () => {
  selectedEnvironment.value = null;
  selectedUserId.value = null;
  selectedCompanyId.value = null;
  fetchData();
};

// Calculate summary statistics
const calculateStats = () => {
  if (!rawData.value || rawData.value.length === 0) {
    stats.value = {
      totalRequests: 0,
      successfulRequests: 0,
      failedRequests: 0,
      promptTokens: 0,
      completionTokens: 0,
      cachedTokens: 0,
      totalTokens: 0,
    };
    return;
  }

  const totalRequests = rawData.value.length;
  const successfulRequests = rawData.value.filter((d) => d.success).length;
  const failedRequests = totalRequests - successfulRequests;

  // Calculate token totals from successful requests only
  const successfulData = rawData.value.filter((d) => d.success);
  const promptTokens = successfulData.reduce((sum, d) => sum + (d.prompt_tokens || 0), 0);
  const completionTokens = successfulData.reduce((sum, d) => sum + (d.completion_tokens || 0), 0);
  const cachedTokens = successfulData.reduce((sum, d) => sum + (d.cached_tokens || 0), 0);
  const totalTokens = successfulData.reduce((sum, d) => sum + (d.total_tokens || 0), 0);

  stats.value = {
    totalRequests,
    successfulRequests,
    failedRequests,
    promptTokens,
    completionTokens,
    cachedTokens,
    totalTokens,
  };
};

// Process data for chart
const processDataForChart = () => {
  let { start, end } = getTimeRange();

  // For "all" time range, use actual data range if available
  if (selectedTimeRange.value === "all" && dateRangeInfo.value && dateRangeInfo.value.actual_start && dateRangeInfo.value.actual_end) {
    start = new Date(dateRangeInfo.value.actual_start);
    end = new Date(dateRangeInfo.value.actual_end);
  }

  const { bucketCount, bucketSize, formatLabel } = getBucketConfig();

  // Create all buckets with zero values (filling gaps)
  const buckets = [];
  const bucketMap = new Map();

  // Generate all time buckets from start to end
  for (let i = 0; i < bucketCount; i++) {
    const bucketTime = new Date(start.getTime() + i * bucketSize);
    const bucket = {
      timestamp: bucketTime,
      promptTokens: 0,
      completionTokens: 0,
      cachedTokens: 0,
      successCount: 0,
      failureCount: 0,
    };
    buckets.push(bucket);
    bucketMap.set(Math.floor(bucketTime.getTime() / bucketSize), bucket);
  }

  // Fill in actual data if available
  if (rawData.value && rawData.value.length > 0) {
    rawData.value.forEach((item) => {
      const timestamp = new Date(item.timestamp);
      const bucketKey = Math.floor(timestamp.getTime() / bucketSize);

      const bucket = bucketMap.get(bucketKey);
      if (bucket) {
        if (item.success) {
          bucket.promptTokens += item.prompt_tokens || 0;
          bucket.completionTokens += item.completion_tokens || 0;
          bucket.cachedTokens += item.cached_tokens || 0;
          bucket.successCount += 1;
        } else {
          bucket.failureCount += 1;
        }
      }
    });
  }

  // Apply cumulative if needed
  if (isCumulative.value) {
    let cumulativePrompt = 0;
    let cumulativeCompletion = 0;
    let cumulativeCached = 0;
    let cumulativeSuccess = 0;
    let cumulativeFailure = 0;

    buckets.forEach((bucket) => {
      cumulativePrompt += bucket.promptTokens;
      cumulativeCompletion += bucket.completionTokens;
      cumulativeCached += bucket.cachedTokens;
      cumulativeSuccess += bucket.successCount;
      cumulativeFailure += bucket.failureCount;

      bucket.promptTokens = cumulativePrompt;
      bucket.completionTokens = cumulativeCompletion;
      bucket.cachedTokens = cumulativeCached;
      bucket.successCount = cumulativeSuccess;
      bucket.failureCount = cumulativeFailure;
    });
  }

  return {
    labels: buckets.map((b) => formatLabel(b.timestamp)),
    promptTokens: buckets.map((b) => b.promptTokens),
    completionTokens: buckets.map((b) => b.completionTokens),
    cachedTokens: buckets.map((b) => b.cachedTokens),
    successCounts: buckets.map((b) => b.successCount),
    failureCounts: buckets.map((b) => b.failureCount),
  };
};

// Activity from log entries (counts per bucket)
const processActivityData = () => {
  const { start } = getTimeRange();
  const { bucketCount, bucketSize, formatLabel } = getBucketConfig();

  const buckets = [];
  for (let i = 0; i < bucketCount; i++) {
    const bucketTime = new Date(start.getTime() + i * bucketSize);
    buckets.push({ timestamp: bucketTime, count: 0 });
  }

  const envMatches = (log) => {
    if (!selectedEnvironment.value) return true;
    const env =
      (log.metrics && log.metrics.company_env) ||
      (log.metrics && log.metrics.company_id && companyEnvById.value[log.metrics.company_id]) ||
      "development";
    return env === selectedEnvironment.value;
  };

  const sourceData =
    logEntries.value && logEntries.value.length
      ? logEntries.value.filter(envMatches)
      : (rawData.value || []).filter(envMatches);

  sourceData.forEach((entry) => {
    const tsRaw = entry.timestamp || entry.created_at;
    const ts = tsRaw ? new Date(tsRaw) : null;
    if (!ts) return;
    const diff = ts.getTime() - start.getTime();
    if (diff < 0) return;
    const bucketIdx = Math.floor(diff / bucketSize);
    if (bucketIdx >= 0 && bucketIdx < buckets.length) {
      buckets[bucketIdx].count += 1;
    }
  });

  return {
    labels: buckets.map((b) => formatLabel(b.timestamp)),
    counts: buckets.map((b) => b.count),
  };
};

// Get bucket configuration (count, size, and label formatter) based on time range
const getBucketConfig = () => {
  switch (selectedTimeRange.value) {
    case "24h":
      return {
        bucketCount: 24,
        bucketSize: 60 * 60 * 1000, // 1 hour
        formatLabel: (date) => date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
      };
    case "7d":
      return {
        bucketCount: 7,
        bucketSize: 24 * 60 * 60 * 1000, // 1 day
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
    case "2w":
      return {
        bucketCount: 14,
        bucketSize: 24 * 60 * 60 * 1000, // 1 day
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
    case "1m":
      return {
        bucketCount: 30,
        bucketSize: 24 * 60 * 60 * 1000, // 1 day
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
    case "2m":
      return {
        bucketCount: 60,
        bucketSize: 24 * 60 * 60 * 1000, // 1 day
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
    case "3m":
      return {
        bucketCount: 90,
        bucketSize: 24 * 60 * 60 * 1000, // 1 day
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
    case "6m":
      return {
        bucketCount: 26,
        bucketSize: 7 * 24 * 60 * 60 * 1000, // 1 week
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
    case "all":
      // Dynamic calculation based on actual data range
      if (dateRangeInfo.value && dateRangeInfo.value.actual_start && dateRangeInfo.value.actual_end) {
        const actualStart = new Date(dateRangeInfo.value.actual_start);
        const actualEnd = new Date(dateRangeInfo.value.actual_end);
        const totalMs = actualEnd - actualStart;
        const totalDays = totalMs / (24 * 60 * 60 * 1000);

        // Decide on bucket size based on data spread
        if (totalDays <= 2) {
          // Less than 2 days: use hourly buckets
          const hours = Math.ceil(totalMs / (60 * 60 * 1000));
          return {
            bucketCount: Math.max(hours, 1),
            bucketSize: 60 * 60 * 1000, // 1 hour
            formatLabel: (date) => date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
          };
        } else if (totalDays <= 90) {
          // 2-90 days: use daily buckets
          return {
            bucketCount: Math.ceil(totalDays),
            bucketSize: 24 * 60 * 60 * 1000, // 1 day
            formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
          };
        } else {
          // More than 90 days: use weekly buckets
          const weeks = Math.ceil(totalDays / 7);
          return {
            bucketCount: weeks,
            bucketSize: 7 * 24 * 60 * 60 * 1000, // 1 week
            formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
          };
        }
      }
      // Fallback if no data
      return {
        bucketCount: 52,
        bucketSize: 7 * 24 * 60 * 60 * 1000, // 1 week
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
    default:
      return {
        bucketCount: 30,
        bucketSize: 24 * 60 * 60 * 1000, // 1 day
        formatLabel: (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      };
  }
};

// Update or create chart
const updateChart = () => {
  if (!chartCanvas.value) return;

  const data = processDataForChart();

  // Destroy existing chart instance
  if (chartInstance) {
    try {
      chartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying chart instance:", e);
    }
    chartInstance = null;
  }

  try {
    const ctx = chartCanvas.value.getContext("2d");

    chartInstance = new Chart(ctx, {
      type: "line",
      data: {
        labels: data.labels,
        datasets: [
          {
            label: t("prompt_tokens"),
            data: data.promptTokens,
            backgroundColor: "rgba(54, 162, 235, 0.5)",
            borderColor: "rgba(54, 162, 235, 1)",
            borderWidth: 1,
            fill: true,
            yAxisID: "y",
            stack: "tokens",
          },
          {
            label: t("completion_tokens"),
            data: data.completionTokens,
            backgroundColor: "rgba(75, 192, 192, 0.5)",
            borderColor: "rgba(75, 192, 192, 1)",
            borderWidth: 1,
            fill: true,
            yAxisID: "y",
            stack: "tokens",
          },
          {
            label: t("cached_tokens"),
            data: data.cachedTokens,
            backgroundColor: "rgba(153, 102, 255, 0.5)",
            borderColor: "rgba(153, 102, 255, 1)",
            borderWidth: 1,
            fill: true,
            yAxisID: "y",
            stack: "tokens",
          },
          {
            label: t("successful_requests"),
            data: data.successCounts,
            backgroundColor: "rgba(75, 192, 75, 0.8)",
            borderColor: "rgba(75, 192, 75, 1)",
            borderWidth: 2,
            fill: false,
            yAxisID: "y1",
            type: "line",
            tension: 0.4,
          },
          {
            label: t("failed_requests"),
            data: data.failureCounts,
            backgroundColor: "rgba(255, 99, 132, 0.8)",
            borderColor: "rgba(255, 99, 132, 1)",
            borderWidth: 2,
            fill: false,
            yAxisID: "y1",
            type: "line",
            tension: 0.4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        interaction: {
          mode: "index",
          intersect: false,
        },
        plugins: {
          title: {
            display: true,
            text: t("token_usage_and_request_status"),
          },
          legend: {
            display: true,
            position: "top",
          },
        },
        scales: {
          y: {
            type: "linear",
            display: true,
            position: "left",
            title: {
              display: true,
              text: t("tokens"),
            },
            beginAtZero: true,
          },
          y1: {
            type: "linear",
            display: true,
            position: "right",
            title: {
              display: true,
              text: t("request_count"),
            },
            beginAtZero: true,
            grid: {
              drawOnChartArea: false,
            },
          },
          x: {
            title: {
              display: true,
              text: t("time"),
            },
            ticks: {
              maxRotation: 45,
              minRotation: 45,
              autoSkip: false,
              font: {
                size: 11,
              },
            },
          },
        },
      },
    });
  } catch (e) {
    console.error("Error creating chart:", e);
    throw e; // Re-throw to be caught by outer try-catch
  }
};

// Update or create classification pie charts
const updateClassificationCharts = () => {
  console.log("updateClassificationCharts called");
  console.log("classifications.value:", classifications.value);
  console.log("hasClassifications:", hasClassifications.value);

  if (!classifications.value) {
    console.log("No classifications data");
    return;
  }

  // Destroy all existing chart instances before creating new ones
  if (promptTypePieChartInstance) {
    try {
      promptTypePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying prompt type chart:", e);
    }
    promptTypePieChartInstance = null;
  }
  if (responseTypePieChartInstance) {
    try {
      responseTypePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying response type chart:", e);
    }
    responseTypePieChartInstance = null;
  }
  if (tonePieChartInstance) {
    try {
      tonePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying tone chart:", e);
    }
    tonePieChartInstance = null;
  }
  if (sourcePieChartInstance) {
    try {
      sourcePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying source chart:", e);
    }
    sourcePieChartInstance = null;
  }

  // Generate colors for pie charts
  const generateColors = (count) => {
    const colors = [
      "rgba(54, 162, 235, 0.8)",
      "rgba(255, 99, 132, 0.8)",
      "rgba(255, 206, 86, 0.8)",
      "rgba(75, 192, 192, 0.8)",
      "rgba(153, 102, 255, 0.8)",
      "rgba(255, 159, 64, 0.8)",
      "rgba(199, 199, 199, 0.8)",
      "rgba(83, 102, 255, 0.8)",
      "rgba(255, 99, 255, 0.8)",
      "rgba(99, 255, 132, 0.8)",
    ];
    return colors.slice(0, count);
  };

  const createPieChart = (canvasRef, data, title, trimLabel = false) => {
    console.log(`Creating chart for ${title}:`, {
      hasCanvas: !!canvasRef.value,
      data: data,
      dataKeys: data ? Object.keys(data) : null,
    });

    if (!canvasRef.value || !data || Object.keys(data).length === 0) {
      console.log(`Skipping chart ${title}: canvas=${!!canvasRef.value}, data=${!!data}, keys=${data ? Object.keys(data).length : 0}`);
      return null;
    }

    const ctx = canvasRef.value.getContext("2d");
    const labels = Object.keys(data);
    const values = Object.values(data);
    const total = values.reduce((a, b) => a + b, 0);
    const colors = generateColors(labels.length);

    console.log(`Creating Chart.js for ${title} with ${labels.length} items`);

    // Create a custom HTML legend plugin
    const htmlLegendPlugin = {
      id: "htmlLegend",
      afterUpdate(chart, args, options) {
        const ul = getOrCreateLegendList(chart, options.containerID);

        // Remove old legend items
        while (ul.firstChild) {
          ul.firstChild.remove();
        }

        // Reuse the built-in legendItems generator
        const items = chart.options.plugins.legend.labels.generateLabels(chart);

        items.forEach((item) => {
          const li = document.createElement("li");
          li.style.alignItems = "center";
          li.style.cursor = "pointer";
          li.style.display = "flex";
          li.style.flexDirection = "row";
          li.style.marginLeft = "10px";
          li.style.marginBottom = "8px";
          li.style.flexBasis = "100%"; // One legend item per row

          li.onclick = () => {
            const { type } = chart.config;
            if (type === "pie" || type === "doughnut") {
              chart.toggleDataVisibility(item.index);
            }
            chart.update();
          };

          // Color box
          const boxSpan = document.createElement("span");
          boxSpan.style.background = item.fillStyle;
          boxSpan.style.borderColor = item.strokeStyle;
          boxSpan.style.borderWidth = item.lineWidth + "px";
          boxSpan.style.display = "inline-block";
          boxSpan.style.flexShrink = "0";
          boxSpan.style.height = "12px";
          boxSpan.style.marginRight = "8px";
          boxSpan.style.width = "12px";
          boxSpan.style.borderRadius = "50%";

          // Text
          const textContainer = document.createElement("span");
          textContainer.style.color = "#ffffff";
          textContainer.style.fontSize = "14px";
          textContainer.style.fontWeight = "600";
          textContainer.style.textDecoration = item.hidden ? "line-through" : "";
          textContainer.style.wordBreak = "break-word";
          textContainer.style.lineHeight = "1.3";

          // Trim text before first "(" if trimLabel is true
          let displayText = item.text;
          if (trimLabel && displayText.includes("(")) {
            displayText = displayText.split("(")[0].trim();
          }

          const text = document.createTextNode(displayText);
          textContainer.appendChild(text);

          li.appendChild(boxSpan);
          li.appendChild(textContainer);
          ul.appendChild(li);
        });
      },
    };

    const getOrCreateLegendList = (chart, id) => {
      const legendContainer = document.getElementById(id);
      let listContainer = legendContainer.querySelector("ul");

      if (!listContainer) {
        listContainer = document.createElement("ul");
        listContainer.style.display = "flex";
        listContainer.style.flexDirection = "row";
        listContainer.style.flexWrap = "wrap";
        listContainer.style.margin = "0";
        listContainer.style.padding = "10px 0 0 0";
        listContainer.style.listStyle = "none";
        listContainer.style.justifyContent = "center";

        legendContainer.appendChild(listContainer);
      }

      return listContainer;
    };

    // Create legend container
    const legendId = `legend-${title.replace(/\s+/g, "-").toLowerCase()}`;
    const cardBody = canvasRef.value.closest(".card-body");
    let legendContainer = cardBody.querySelector(`#${legendId}`);

    if (!legendContainer) {
      legendContainer = document.createElement("div");
      legendContainer.id = legendId;
      legendContainer.style.marginTop = "10px";
      cardBody.appendChild(legendContainer);
    }

    return new Chart(ctx, {
      type: "pie",
      data: {
        labels: labels,
        datasets: [
          {
            data: values,
            backgroundColor: colors,
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          htmlLegend: {
            containerID: legendId,
          },
          legend: {
            display: false, // Hide default legend, use custom HTML legend instead
            labels: {
              generateLabels: (chart) => {
                const data = chart.data;
                if (data.labels.length && data.datasets.length) {
                  return data.labels.map((label, i) => {
                    const value = data.datasets[0].data[i];
                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                    const labelText = `${label} (${percentage}%)`;
                    return {
                      text: labelText,
                      fillStyle: data.datasets[0].backgroundColor[i],
                      strokeStyle: data.datasets[0].borderColor ? data.datasets[0].borderColor[i] : data.datasets[0].backgroundColor[i],
                      lineWidth: 0,
                      hidden: false,
                      index: i,
                    };
                  });
                }
                return [];
              },
            },
          },
          tooltip: {
            callbacks: {
              title: function () {
                // Return empty to hide the title line
                return "";
              },
              label: function (context) {
                let label = context.label || "";

                // Trim label before first "(" if trimLabel is true
                if (trimLabel && label.includes("(")) {
                  label = label.split("(")[0].trim();
                }

                const value = context.parsed || 0;
                const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                return `${label}: ${value} (${percentage}%)`;
              },
            },
          },
          datalabels: {
            color: "#fff",
            font: {
              weight: "bold",
              size: 13,
            },
            formatter: (value, context) => {
              const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
              // Only show percentage if it's greater than 5% to avoid clutter
              return percentage > 5 ? `${percentage}%` : "";
            },
          },
        },
      },
      plugins: [ChartDataLabels, htmlLegendPlugin],
    });
  };

  // Update all four classification charts
  console.log("Creating prompt_type chart");
  promptTypePieChartInstance = createPieChart(promptTypePieChart, classifications.value.prompt_type, t("prompt_type_distribution"), true);

  console.log("Creating response_type chart");
  responseTypePieChartInstance = createPieChart(responseTypePieChart, classifications.value.response_type, t("response_type_distribution"), true);

  console.log("Creating tone chart");
  tonePieChartInstance = createPieChart(tonePieChart, classifications.value.tone, t("tone_distribution"), false);

  console.log("Creating source chart");
  sourcePieChartInstance = createPieChart(sourcePieChart, classifications.value.source, t("source_distribution"), false);

  console.log("Classification charts created:", {
    promptType: !!promptTypePieChartInstance,
    responseType: !!responseTypePieChartInstance,
    tone: !!tonePieChartInstance,
    source: !!sourcePieChartInstance,
  });
};

// RAG class mass distribution (text length per class)
const updateClassMassChart = () => {
  if (!classMassChart.value) return;

  if (classMassChartInstance) {
    try {
      classMassChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying class mass chart:", e);
    }
    classMassChartInstance = null;
  }

  const byClass = metadataClassMass.value?.by_class || {};
  const labels = Object.keys(byClass);
  if (!labels.length) return;

  const lengths = labels.map((k) => byClass[k]?.text_length || 0);
  const total = lengths.reduce((a, b) => a + b, 0);
  const colors = [
    "rgba(54, 162, 235, 0.8)",
    "rgba(255, 99, 132, 0.8)",
    "rgba(255, 206, 86, 0.8)",
    "rgba(75, 192, 192, 0.8)",
    "rgba(153, 102, 255, 0.8)",
    "rgba(255, 159, 64, 0.8)",
    "rgba(199, 199, 199, 0.8)",
  ];

  const ctx = classMassChart.value.getContext("2d");
  classMassChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [
        {
          data: lengths,
          backgroundColor: colors.slice(0, labels.length),
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { position: "bottom" },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const label = ctx.label || "";
              const value = ctx.raw || 0;
              const pct = total ? ((value / total) * 100).toFixed(1) : 0;
              const count = byClass[label]?.count ?? 0;
              return `${label}: ${value.toLocaleString()} ${t("text_length_chars")} (${pct}%) • ${count} ${t("documents")}`;
            },
          },
        },
      },
    },
  });
};

// RAG class usage (doc count per class)
const updateClassUsageChart = () => {
  if (!classUsageChart.value) return;

  if (classUsageChartInstance) {
    try {
      classUsageChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying class usage chart:", e);
    }
    classUsageChartInstance = null;
  }

  const byClass = ragClassUsage.value?.by_class || {};
  const labels = Object.keys(byClass);
  if (!labels.length) return;

  const counts = labels.map((k) => byClass[k] || 0);

  const ctx = classUsageChart.value.getContext("2d");
  classUsageChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: t("documents"),
          data: counts,
          backgroundColor: "rgba(54, 162, 235, 0.6)",
          borderColor: "rgba(54, 162, 235, 1)",
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.formattedValue} ${t("documents")}`,
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: t("documents") },
        },
      },
    },
  });
};

// Simple Sankey-like SVG render (prompt -> response -> rag class)
const drawSankeyChart = () => {
  if (!sankeySvg.value) return;

  // Clear previous
  while (sankeySvg.value.firstChild) {
    sankeySvg.value.removeChild(sankeySvg.value.firstChild);
  }

  if (!sankeyLinks.value.length || !sankeyNodes.value.length) return;

  const svgNS = "http://www.w3.org/2000/svg";
  const padding = 10;
  const svgW = sankeySvg.value?.parentElement?.clientWidth || sankeyWidth.value;
  // Use three columns, but compress width per column to leave more margin for rightmost labels
  const colWidth = (svgW - 2 * padding) / 2.4;
  const nodeHeight = 52;
  const nodeMargin = 15;
  const groupColors = {
    prompt: "#0d6efd",
    response: "#20c997",
    rag: "#6f42c1",
  };
  const linkColors = {
    prompt: "rgba(13,110,253,0.5)",
    response: "rgba(32,201,151,0.5)",
    rag: "rgba(111,66,193,0.5)",
    default: "rgba(54,162,235,0.5)",
  };

  const columns = {
    prompt: [],
    response: [],
    rag: [],
  };

  sankeyNodes.value.forEach((n, idx) => {
    columns[n.group].push({ ...n, idx });
  });

  // Assign positions
  const positions = {};
  const nodeByIdx = {};
  ["prompt", "response", "rag"].forEach((colKey, colIdx) => {
    const colNodes = columns[colKey];
    colNodes.sort((a, b) => a.name.localeCompare(b.name));
    colNodes.forEach((n, i) => {
      const x = padding + colIdx * colWidth;
      const y = padding + i * (nodeHeight + nodeMargin);
      positions[n.idx] = { x, y };
      nodeByIdx[n.idx] = n;
    });
  });

  const maxVal = Math.max(...sankeyLinks.value.map((l) => l.value));
  const totalVal = sankeyLinks.value.reduce((acc, l) => acc + (l.value || 0), 0) || 1;

  // Draw links
  sankeyLinks.value.forEach((link) => {
    const source = positions[link.source];
    const target = positions[link.target];
    if (!source || !target) return;
    const path = document.createElementNS(svgNS, "path");
    const thickness = 2 + (link.value / maxVal) * 8;
    const x1 = source.x + 150;
    const y1 = source.y + nodeHeight / 2;
    const x2 = target.x;
    const y2 = target.y + nodeHeight / 2;
    const mx = (x1 + x2) / 2;
    const srcNode = nodeByIdx[link.source];
    const color = srcNode ? (linkColors[srcNode.group] || linkColors.default) : linkColors.default;
    path.setAttribute("d", `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", thickness);
    path.setAttribute("stroke-linecap", "round");

    const pct = ((link.value || 0) / totalVal) * 100;
    const title = document.createElementNS(svgNS, "title");
    title.textContent = `${link.value} (${pct.toFixed(1)}%)`;
    path.appendChild(title);

    sankeySvg.value.appendChild(path);
  });

  // Draw nodes
  Object.entries(columns).forEach(([colKey, colNodes]) => {
    colNodes.forEach((n) => {
      const pos = positions[n.idx];
      if (!pos) return;
      const rect = document.createElementNS(svgNS, "rect");
      rect.setAttribute("x", pos.x);
      rect.setAttribute("y", pos.y);
      rect.setAttribute("width", 160);
      rect.setAttribute("height", nodeHeight);
      rect.setAttribute("rx", 4);
      rect.setAttribute("fill", groupColors[n.group] || "#0d6efd");
      rect.setAttribute("opacity", "0.8");
      sankeySvg.value.appendChild(rect);

      // Draw wrapped text
      const words = n.name.split(" ");
      const lineHeight = 13;
      let line = "";
      let lineCount = 0;
      words.forEach((word, idx) => {
        const testLine = line + word + " ";
        if (testLine.length > 26) {
          const t = document.createElementNS(svgNS, "text");
          t.setAttribute("x", pos.x + 8);
          t.setAttribute("y", pos.y + 12 + lineCount * lineHeight);
          t.setAttribute("fill", "#ffffff");
          t.setAttribute("font-size", "12");
          t.textContent = line.trim();
          sankeySvg.value.appendChild(t);
          line = word + " ";
          lineCount += 1;
        } else {
          line = testLine;
        }
        if (idx === words.length - 1) {
          const t = document.createElementNS(svgNS, "text");
          t.setAttribute("x", pos.x + 8);
          t.setAttribute("y", pos.y + 12 + lineCount * lineHeight);
          t.setAttribute("fill", "#ffffff");
          t.setAttribute("font-size", "12");
          t.textContent = line.trim();
          sankeySvg.value.appendChild(t);
        }
      });
    });
  });
};

// Radar chart for axes defined in settings
const updateRadarChart = () => {
  radarHasData.value = false;
  radarDebug.value = radarDebug.value || "";
  if (!radarChart.value) return;

  if (radarChartInstance) {
    try {
      radarChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying radar chart:", e);
    }
    radarChartInstance = null;
  }

  const metrics = computeRadarMetrics();
  if (!metrics || !metrics.labels.length) {
    if (!radarDebug.value) radarDebug.value = "Radar metrics not available.";
    return;
  }

  const ctx = radarChart.value.getContext("2d");
  const toPercentSeries = (series) => {
    const total = series.reduce((a, b) => a + (b || 0), 0);
    if (!total) return series.map(() => 0);
    return series.map((v) => Math.round(((v || 0) / total) * 1000) / 10); // one decimal
  };
  const usePercent = false;
  const promptPercent = toPercentSeries(metrics.promptSeries);
  const ragPercent = toPercentSeries(metrics.ragSeries);
  const promptTotal = metrics.promptSeries.reduce((a, b) => a + (b || 0), 0);
  const ragTotal = metrics.ragSeries.reduce((a, b) => a + (b || 0), 0);
  const promptData = metrics.promptSeries;
  const ragData = metrics.ragSeries;
  const maxValue = Math.max(...promptData, ...ragData, 1);
  const suggestedMax = maxValue <= 5 ? 5 : maxValue + 1;
  const stepSize = maxValue <= 10 ? 1 : Math.ceil(maxValue / 5);

  radarChartInstance = new Chart(ctx, {
    type: "radar",
    data: {
      labels: metrics.labels,
      datasets: [
        {
          label: t("prompt_type_distribution"),
          data: promptData,
          rawCounts: metrics.promptSeries,
          totalCount: promptTotal,
          isPercent: usePercent,
          backgroundColor: "rgba(13,110,253,0.18)",
          borderColor: "#0d6efd",
          borderWidth: 2,
          pointBackgroundColor: "#0d6efd",
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
        },
        {
          label: t("rag_document_taxonomy"),
          data: ragData,
          rawCounts: metrics.ragSeries,
          totalCount: ragTotal,
          isPercent: usePercent,
          backgroundColor: "rgba(111,66,193,0.16)",
          borderColor: "#6f42c1",
          borderWidth: 2,
          pointBackgroundColor: "#6f42c1",
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      elements: {
        line: {
          tension: 0.2,
        },
      },
      scales: {
        r: {
          beginAtZero: true,
          suggestedMax,
          ticks: {
            display: true,
            precision: 0,
            stepSize,
            callback: (value) => value,
          },
          angleLines: { color: "rgba(255,255,255,0.12)" },
          grid: { color: "rgba(255,255,255,0.12)" },
          pointLabels: {
            font: { size: 13 },
            color: "#adb5bd",
          },
        },
      },
      plugins: {
        legend: { position: "top", labels: { usePointStyle: true, boxWidth: 10 } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const rawCounts = ctx.dataset?.rawCounts || [];
              const raw = rawCounts[ctx.dataIndex] ?? ctx.raw;
              const total = ctx.dataset?.totalCount || 0;
              const pct = total ? ((raw / total) * 100).toFixed(1) : "0.0";
              const displayVal = ctx.dataset?.isPercent ? `${ctx.raw}%` : `${raw}`;
              return `${ctx.dataset?.label || ""}: ${displayVal} (${pct}%)`;
            },
          },
        },
      },
      layout: {
        padding: {
          top: 10,
          right: 20,
          bottom: 20,
          left: 20,
        },
      },
    },
  });

  radarHasData.value = true;
};

const normalizeLabel = (value) => (value || "").toString().toLowerCase().trim();

const baseHorizonDefaults = () => ({
  short_term: t("time_horizon_short") || "Short term",
  mid_term: t("time_horizon_mid") || "Mid term",
  long_term: t("time_horizon_long") || "Long term",
  unmapped: t("time_horizon_unmapped") || "Unmapped",
});

const getTimeHorizonConfig = () => {
  const defaults = baseHorizonDefaults();
  const configured = settingsData.value?.time_horizons || settingsData.value?.analytics?.time_horizons || [];
  const merged = [];
  const seen = new Set();
  [...configured, ...Object.keys(defaults).map((key) => ({ key, label: defaults[key] }))].forEach((h) => {
    const key = normalizeLabel(h?.key || h?.name || h?.id);
    if (!key || seen.has(key)) return;
    const fallbackLabel = defaults[key] || h?.key || key;
    merged.push({ key, label: h?.label || h?.name || fallbackLabel });
    seen.add(key);
  });
  if (!merged.some((h) => h.key === "unmapped")) {
    merged.push({ key: "unmapped", label: defaults.unmapped });
  }
  return merged;
};

const defaultPromptHorizonRules = {
  "operational decisions": "short_term",
  "tactical decisions": "mid_term",
  "strategic decisions": "long_term",
};

const defaultRagHorizonRules = {
  "operations and processes": "short_term",
  "technology and information systems": "mid_term",
  "human resources and organizational capabilities": "mid_term",
  "organizational profile": "mid_term",
  "business domain and market environment": "mid_term",
  "financial structure and performance": "mid_term",
  "governance and compliance": "long_term",
  "strategic orientation": "long_term",
  "strategic objectives and goals": "long_term",
  "external relations and partnerships": "mid_term",
};

const buildTimeHorizonMappings = () => {
  const horizons = getTimeHorizonConfig();
  const validKeys = new Set(horizons.map((h) => h.key));
  const promptMap = {};
  const ragMap = {};
  const promptSettings = settingsData.value?.prompt_time_horizons || settingsData.value?.analytics?.prompt_time_horizons || [];
  const ragSettings = settingsData.value?.rag_time_horizons || settingsData.value?.analytics?.rag_time_horizons || [];

  promptSettings.forEach((m) => {
    const cls = normalizeLabel(m?.class || m?.prompt_class);
    const hz = normalizeLabel(m?.horizon || m?.time_horizon || m?.bucket);
    if (cls && hz && validKeys.has(hz)) {
      promptMap[cls] = hz;
    }
  });
  Object.entries(defaultPromptHorizonRules).forEach(([cls, hz]) => {
    if (!promptMap[cls] && validKeys.has(hz)) {
      promptMap[cls] = hz;
    }
  });

  ragSettings.forEach((m) => {
    const cls = normalizeLabel(m?.class || m?.rag_class);
    const hz = normalizeLabel(m?.horizon || m?.time_horizon || m?.bucket);
    if (cls && hz && validKeys.has(hz)) {
      ragMap[cls] = hz;
    }
  });
  Object.entries(defaultRagHorizonRules).forEach(([cls, hz]) => {
    if (!ragMap[cls] && validKeys.has(hz)) {
      ragMap[cls] = hz;
    }
  });

  return { horizons, promptMap, ragMap };
};

const getPromptCounts = () => {
  if (classifications.value?.prompt_type && Object.keys(classifications.value.prompt_type).length) {
    return classifications.value.prompt_type;
  }
  const counts = {};
  turnClassifications.value.forEach((turn) => {
    const key = normalizeLabel(turn?.prompt_type);
    if (!key) return;
    counts[turn.prompt_type] = (counts[turn.prompt_type] || 0) + 1;
  });
  return counts;
};

const getRagCounts = () => {
  if (ragClassUsage.value?.by_class && Object.keys(ragClassUsage.value.by_class).length) {
    return ragClassUsage.value.by_class;
  }
  const counts = {};
  turnClassifications.value.forEach((turn) => {
    if (!Array.isArray(turn?.rag_classes)) return;
    turn.rag_classes.forEach((rc) => {
      const label = rc?.class || rc;
      if (!label) return;
      counts[label] = (counts[label] || 0) + 1;
    });
  });
  return counts;
};

const buildHorizonSummary = () => {
  const { horizons, promptMap, ragMap } = buildTimeHorizonMappings();
  if (!horizons.length) return null;
  const promptCounts = getPromptCounts();
  const ragCounts = getRagCounts();

  const rollup = (counts, mapping) => {
    const totals = {};
    Object.entries(counts || {}).forEach(([label, count]) => {
      const hz = mapping[normalizeLabel(label)] || "unmapped";
      totals[hz] = (totals[hz] || 0) + (count || 0);
    });
    // ensure all horizons exist
    horizons.forEach((h) => {
      if (!totals[h.key]) totals[h.key] = 0;
    });
    return totals;
  };

  const promptTotals = rollup(promptCounts, promptMap);
  const ragTotals = rollup(ragCounts, ragMap);

  return {
    horizons,
    promptTotals,
    ragTotals,
  };
};

const renderTimeHorizonChart = () => {
  const data = buildHorizonSummary();
  if (!timeHorizonChart.value || !data) return;

  if (timeHorizonChartInstance) {
    try {
      timeHorizonChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying time horizon chart:", e);
    }
    timeHorizonChartInstance = null;
  }

  // Use configured order but invert for vertical axis so the first horizon appears at the bottom.
  const displayHorizons = [...data.horizons].reverse();
  const labels = displayHorizons.map((h) => h.label);

  const totalPrompts = Object.values(data.promptTotals || {}).reduce((a, b) => a + (b || 0), 0);
  const totalRag = Object.values(data.ragTotals || {}).reduce((a, b) => a + (b || 0), 0);
  const promptCounts = displayHorizons.map((h) => data.promptTotals[h.key] || 0);
  const ragCounts = displayHorizons.map((h) => data.ragTotals[h.key] || 0);
  const usePercent = true;
  const promptData = promptCounts.map((count) => {
    if (!usePercent) return (count || 0) * -1;
    return totalPrompts ? ((count / totalPrompts) * 100) * -1 : 0;
  });
  const ragData = ragCounts.map((count) => {
    if (!usePercent) return count || 0;
    return totalRag ? (count / totalRag) * 100 : 0;
  });
  const maxAbs = usePercent ? 100 : Math.max(...promptCounts.map((v) => Math.abs(v)), ...ragCounts, 1) * 1.1;

  const ctx = timeHorizonChart.value.getContext("2d");
  timeHorizonChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: t("time_horizon_prompts"),
          data: promptData,
          rawCounts: promptCounts,
          totalCount: totalPrompts,
          isPercent: usePercent,
          backgroundColor: "rgba(13, 110, 253, 0.6)",
          borderColor: "#0d6efd",
          borderWidth: 1,
        },
        {
          label: t("time_horizon_rag_documents"),
          data: ragData,
          rawCounts: ragCounts,
          totalCount: totalRag,
          isPercent: usePercent,
          backgroundColor: "rgba(111, 66, 193, 0.55)",
          borderColor: "#6f42c1",
          borderWidth: 1,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { position: "top", labels: { usePointStyle: true, boxWidth: 10 } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const rawCounts = ctx.dataset?.rawCounts || [];
              const raw = rawCounts[ctx.dataIndex] ?? Math.abs(ctx.raw || 0);
              const total = ctx.dataset?.totalCount || 0;
              const pct = total ? ((raw / total) * 100).toFixed(1) : "0.0";
              const displayVal = ctx.dataset?.isPercent
                ? `${Math.abs(ctx.raw || 0).toFixed(1)}%`
                : `${Math.abs(ctx.raw || 0)}`;
              return `${ctx.dataset?.label || ""}: ${displayVal} (${raw} | ${pct}%)`;
            },
          },
        },
      },
      scales: {
        y: {
          title: { display: true, text: t("time_horizon") },
        },
        x: {
          min: -maxAbs,
          max: maxAbs,
          ticks: {
            callback: (value) => (usePercent ? `${Math.abs(value)}%` : Math.abs(value)),
          },
          title: { display: true, text: usePercent ? `${t("time_horizon_distribution")} (%)` : t("time_horizon_distribution") },
          grid: {
            color: (ctx) => (ctx.tick?.value === 0 ? "rgba(0,0,0,0.35)" : "rgba(0,0,0,0.08)"),
            lineWidth: (ctx) => (ctx.tick?.value === 0 ? 2 : 1),
          },
        },
      },
    },
  });
};

// Metadata distribution chart (by source/type)
const updateMetadataChart = () => {
  if (!metadataChart.value) return;

  if (metadataChartInstance) {
    try {
      metadataChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying metadata chart:", e);
    }
    metadataChartInstance = null;
  }

  const bySource = metadataStats.value?.by_source || {};
  const labels = Object.keys(bySource);
  const values = Object.values(bySource);

  // If no data, show zeroed defaults to avoid empty cards
  if (!labels.length) {
    ["google_drive", "onedrive", "email", "manual_upload", "metadata"].forEach((src) => {
      if (!(src in bySource)) {
        bySource[src] = 0;
      }
    });
  }

  const colors = [
    "rgba(54, 162, 235, 0.8)",
    "rgba(75, 192, 192, 0.8)",
    "rgba(255, 206, 86, 0.8)",
    "rgba(255, 99, 132, 0.8)",
    "rgba(153, 102, 255, 0.8)",
  ];

  const ctx = metadataChart.value.getContext("2d");
  metadataChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: Object.keys(bySource).map((l) => formatMetadataSource(l)),
      datasets: [
        {
          data: Object.keys(bySource).map((k) => bySource[k]),
          backgroundColor: colors.slice(0, Object.keys(bySource).length),
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { position: "bottom" },
        title: { display: false },
      },
    },
  });
};

// Activity over time using log entries
const updateActivityChart = () => {
  if (!activityChart.value) return;

  if (activityChartInstance) {
    try {
      activityChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying activity chart:", e);
    }
    activityChartInstance = null;
  }

  const { labels, counts } = processActivityData();
  if (!labels.length) return;

  const ctx = activityChart.value.getContext("2d");
  activityChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: t("requests"),
          data: counts,
          backgroundColor: "rgba(54, 162, 235, 0.4)",
          borderColor: "rgba(54, 162, 235, 1)",
          borderWidth: 2,
          fill: true,
          tension: 0.4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { position: "bottom" },
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: t("request_count") },
        },
        x: {
          ticks: { maxRotation: 45, minRotation: 45, autoSkip: false },
          title: { display: true, text: t("time") },
        },
      },
    },
  });
};

// Prompt length distribution (question_length) histogram
const updatePromptLengthChart = () => {
  if (!promptLengthChart.value) return;

  if (promptLengthChartInstance) {
    try {
      promptLengthChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying prompt length chart:", e);
    }
    promptLengthChartInstance = null;
  }

  const envMatches = (log) => {
    if (!selectedEnvironment.value) return true;
    const env =
      (log.metrics && log.metrics.company_env) ||
      (log.metrics && log.metrics.company_id && companyEnvById.value[log.metrics.company_id]) ||
      "development";
    return env === selectedEnvironment.value;
  };

  const lengths = (logEntries.value || [])
    .filter(envMatches)
    .map((log) => (log.metrics && typeof log.metrics.question_length === "number" ? log.metrics.question_length : null))
    .filter((v) => v !== null && v >= 0);

  // If no lengths, show empty chart with zeroed bars to avoid blank card
  if (!lengths.length) {
    const ctx = promptLengthChart.value.getContext("2d");
    promptLengthChartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["0-50", "51-100", "101-200", "201-400", "401-800", "801+"],
        datasets: [
          {
            label: t("prompt_length_distribution"),
            data: [0, 0, 0, 0, 0, 0],
            backgroundColor: "rgba(153, 102, 255, 0.2)",
            borderColor: "rgba(153, 102, 255, 0.6)",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
        },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: t("request_count") } },
          x: { title: { display: true, text: t("prompt_length_chars") } },
        },
      },
    });
    return;
  }

  const buckets = [
    { label: "0-50", min: 0, max: 50 },
    { label: "51-100", min: 51, max: 100 },
    { label: "101-200", min: 101, max: 200 },
    { label: "201-400", min: 201, max: 400 },
    { label: "401-800", min: 401, max: 800 },
    { label: "801+", min: 801, max: Infinity },
  ];

  const counts = buckets.map(({ min, max }) => lengths.filter((v) => v >= min && v <= max).length);

  const ctx = promptLengthChart.value.getContext("2d");
  promptLengthChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: buckets.map((b) => b.label),
      datasets: [
        {
          label: t("prompt_length_distribution"),
          data: counts,
          backgroundColor: "rgba(153, 102, 255, 0.6)",
          borderColor: "rgba(153, 102, 255, 1)",
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: t("request_count") },
        },
        x: {
          title: { display: true, text: t("prompt_length_chars") },
        },
      },
    },
  });
};

onMounted(() => {
  fetchData();
  loadReportScripts();
});

onUnmounted(() => {
  // Clean up all chart instances
  if (chartInstance) {
    try {
      chartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying main chart on unmount:", e);
    }
  }
  if (promptTypePieChartInstance) {
    try {
      promptTypePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying prompt type chart on unmount:", e);
    }
  }
  if (responseTypePieChartInstance) {
    try {
      responseTypePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying response type chart on unmount:", e);
    }
  }
  if (tonePieChartInstance) {
    try {
      tonePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying tone chart on unmount:", e);
    }
  }
  if (sourcePieChartInstance) {
    try {
      sourcePieChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying source chart on unmount:", e);
    }
  }
  if (metadataChartInstance) {
    try {
      metadataChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying metadata chart on unmount:", e);
    }
  }
  if (classMassChartInstance) {
    try {
      classMassChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying class mass chart on unmount:", e);
    }
  }
  if (classUsageChartInstance) {
    try {
      classUsageChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying class usage chart on unmount:", e);
    }
  }
  if (activityChartInstance) {
    try {
      activityChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying activity chart on unmount:", e);
    }
  }
  if (promptLengthChartInstance) {
    try {
      promptLengthChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying prompt length chart on unmount:", e);
    }
  }
  if (timeHorizonChartInstance) {
    try {
      timeHorizonChartInstance.destroy();
    } catch (e) {
      console.warn("Error destroying time horizon chart on unmount:", e);
    }
  }
});
</script>

<style scoped>
/* Maximize horizontal space usage */
.container-fluid {
  max-width: 99%;
  padding-left: 15px;
  padding-right: 15px;
}

.card {
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

canvas {
  max-height: 500px;
}

/* Ensure all stat cards have consistent height */
.stat-card {
  height: 100%;
  min-height: 140px;
}

.stat-card .card-body {
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
}

/* Classification charts - responsive layout:
   - xxl (1400px+): 4 charts in a row (col-xxl-3)
   - xl (1200px-1399px): 2x2 grid (col-xl-6)
   - md (768px-1199px): 2x2 grid (col-md-6)
   - sm (<768px): 1 chart per row
*/
.classification-chart-card {
  min-height: 500px;
}

.classification-chart-card canvas:not(.radar-canvas) {
  max-height: 300px;
}
.radar-canvas {
  width: 100%;
  height: 520px;
  min-height: 520px;
}
.time-horizon-chart canvas {
  max-height: 360px;
}

/* Responsive adjustments */
@media (max-width: 1399px) {
  /* On xl and below, show 2x2 grid */
  .classification-chart-card {
    min-height: 480px;
  }
}

@media (max-width: 767px) {
  /* On small screens, show 1 chart per row */
  .classification-chart-card {
    min-height: 400px;
  }

  .container-fluid {
    max-width: 100%;
  }
}
</style>
