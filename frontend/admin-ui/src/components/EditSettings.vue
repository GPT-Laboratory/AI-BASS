<template>
  <div v-if="true">
    <h2>{{ $t("settings") }}</h2>

    <div class="card mt-4">
      <div class="card-body">
        <h5 class="card-title">
          {{ $t("system_settings") }}
        </h5>

        <div class="mb-3">
          <label class="form-label">{{ $t("global_system_prompt") }}</label>
          <textarea class="form-control" v-model="settings.global_system_prompt"
            :placeholder="$t('enter_global_system_prompt')" rows="3"></textarea>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("whatsapp_error_message") }}</label>
          <textarea class="form-control" v-model="settings.whatsapp_error_message"
            :placeholder="$t('enter_whatsapp_error_message')" rows="3"></textarea>
        </div>

        <!-- NEW FIELD: memory_generation_prompt -->
        <div class="mb-3">
          <label class="form-label">{{ $t("memory_generation_prompt") }}</label>
          <textarea class="form-control" v-model="settings.memory_generation_prompt"
            :placeholder="$t('enter_memory_generation_prompt')" rows="10"></textarea>
          <small class="form-text text-muted">
            {{ $t("memory_generation_prompt_help") }}
          </small>
        </div>

        <!-- NEW FIELD: reminder_inactive_hours -->
        <div class="mb-3">
          <label class="form-label">{{ $t("reminder_inactive_hours") }}</label>
          <input type="number" class="form-control" v-model.number="settings.reminder_inactive_hours"
            :placeholder="$t('enter_reminder_inactive_hours')" />
        </div>

        <!-- LightRAG Configuration Section -->
        <h6 class="mt-4 mb-3 text-primary">{{ $t("lightrag_configuration") }}</h6>

        <!-- LightRAG Chunking Settings -->
        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_chunk_token_size") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_chunk_token_size"
            :placeholder="$t('enter_lightrag_chunk_token_size')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_chunk_token_size_help") }}
          </small>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_chunk_overlap_size") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_chunk_overlap_size"
            :placeholder="$t('enter_lightrag_chunk_overlap_size')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_chunk_overlap_size_help") }}
          </small>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_entity_extract_max_gleaning") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_entity_extract_max_gleaning"
            :placeholder="$t('enter_lightrag_entity_extract_max_gleaning')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_entity_extract_max_gleaning_help") }}
          </small>
        </div>

        <!-- LightRAG Query Settings -->
        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_query_top_k") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_query_top_k"
            :placeholder="$t('enter_lightrag_query_top_k')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_query_top_k_help") }}
          </small>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_query_max_tokens") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_query_max_tokens"
            :placeholder="$t('enter_lightrag_query_max_tokens')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_query_max_tokens_help") }}
          </small>
        </div>

        <!-- LightRAG Performance Settings -->
        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_max_async_llm") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_max_async_llm"
            :placeholder="$t('enter_lightrag_max_async_llm')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_max_async_llm_help") }}
          </small>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_max_async_embedding") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_max_async_embedding"
            :placeholder="$t('enter_lightrag_max_async_embedding')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_max_async_embedding_help") }}
          </small>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_embedding_batch_size") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_embedding_batch_size"
            :placeholder="$t('enter_lightrag_embedding_batch_size')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_embedding_batch_size_help") }}
          </small>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("lightrag_max_parallel_insert") }}</label>
          <input type="number" class="form-control" v-model.number="settings.lightrag_max_parallel_insert"
            :placeholder="$t('enter_lightrag_max_parallel_insert')" />
          <small class="form-text text-muted">
            {{ $t("lightrag_max_parallel_insert_help") }}
          </small>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("prompt_classification") }}</label>
          <div v-for="(value, index) in settings.prompt_classification" :key="index" class="input-group mb-2">
            <input type="text" class="form-control" v-model="settings.prompt_classification[index]"
              :placeholder="$t('enter_value')" />
            <button type="button" class="btn btn-outline-danger" @click="removeValue('prompt_classification', index)">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <br />
          <button type="button" class="btn btn-outline-primary mt-2" @click="addValue('prompt_classification')">
            <i class="bi bi-plus-lg"></i>
          </button>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("response_classification") }}</label>
          <div v-for="(value, index) in settings.response_classification" :key="index" class="input-group mb-2">
            <input type="text" class="form-control" v-model="settings.response_classification[index]"
              :placeholder="$t('enter_value')" />
            <button type="button" class="btn btn-outline-danger" @click="removeValue('response_classification', index)">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <br />
          <button type="button" class="btn btn-outline-primary mt-2" @click="addValue('response_classification')">
            <i class="bi bi-plus-lg"></i>
          </button>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("interaction_tone_classification") }}</label>
          <div v-for="(value, index) in settings.interaction_tone_classification" :key="index" class="input-group mb-2">
            <input type="text" class="form-control" v-model="settings.interaction_tone_classification[index]"
              :placeholder="$t('enter_value')" />
            <button type="button" class="btn btn-outline-danger"
              @click="removeValue('interaction_tone_classification', index)">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <br />
          <button type="button" class="btn btn-outline-primary mt-2"
            @click="addValue('interaction_tone_classification')">
            <i class="bi bi-plus-lg"></i>
          </button>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("rag_document_taxonomy") }}</label>
          <small class="form-text text-muted d-block mb-2">{{ $t("rag_document_taxonomy_help") }}</small>
          <div v-for="(value, index) in settings.rag_document_taxonomy" :key="index" class="input-group mb-2">
            <input type="text" class="form-control" v-model="settings.rag_document_taxonomy[index]"
              :placeholder="$t('enter_value')" />
            <button type="button" class="btn btn-outline-danger" @click="removeValue('rag_document_taxonomy', index)">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <br />
          <button type="button" class="btn btn-outline-primary mt-2" @click="addValue('rag_document_taxonomy')">
            <i class="bi bi-plus-lg"></i>
          </button>
        </div>

        <!-- Radar axes mapping -->
        <div class="mb-3">
          <label class="form-label">{{ $t("radar_axes") }}</label>
          <small class="form-text text-muted d-block mb-2">{{ $t("radar_axes_help") }}</small>
          <div v-for="(axis, axisIndex) in settings.radar_axes" :key="axisIndex" class="mb-3 border rounded p-3">
            <div class="mb-2 d-flex align-items-center gap-2">
              <input type="text" class="form-control" v-model="axis.name" :placeholder="$t('axis_name')" />
              <button type="button" class="btn btn-outline-danger" @click="removeAxis(axisIndex)">
                <i class="bi bi-x-lg"></i>
              </button>
            </div>
            <div class="mb-2">
              <label class="form-label">{{ $t("prompt_classes") }}</label>
              <select class="form-select" multiple v-model="axis.prompt_classes">
                <option v-for="opt in settings.prompt_classification" :key="`pc-opt-${axisIndex}-${opt}`" :value="opt">
                  {{ opt }}
                </option>
              </select>
              <small class="form-text text-muted">{{ $t("select_multiple_hint") }}</small>
            </div>
            <div class="mb-2">
              <label class="form-label">{{ $t("rag_classes") }}</label>
              <select class="form-select" multiple v-model="axis.rag_classes">
                <option v-for="opt in settings.rag_document_taxonomy" :key="`rc-opt-${axisIndex}-${opt}`" :value="opt">
                  {{ opt }}
                </option>
              </select>
              <small class="form-text text-muted">{{ $t("select_multiple_hint") }}</small>
            </div>
          </div>
          <button type="button" class="btn btn-outline-primary mt-2" @click="addAxis">
            <i class="bi bi-plus-lg"></i> {{ $t("add_axis") }}
          </button>
        </div>

        <!-- Time horizon configuration -->
        <div class="mb-3">
          <label class="form-label">{{ $t("time_horizon_categories") }}</label>
          <small class="form-text text-muted d-block mb-2">{{ $t("time_horizon_categories_help") }}</small>
          <div class="row g-3">
            <div class="col-md-4" v-for="(horizon, idx) in settings.time_horizons" :key="`hz-${horizon.key}-${idx}`">
              <div class="input-group">
                <span class="input-group-text text-muted" style="min-width: 110px">{{ horizon.key }}</span>
                <input
                  type="text"
                  class="form-control"
                  v-model="settings.time_horizons[idx].label"
                  :placeholder="$t('time_horizon_label')"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Prompt time horizon mapping -->
        <div class="mb-3">
          <label class="form-label">{{ $t("prompt_time_horizon_mapping") }}</label>
          <small class="form-text text-muted d-block mb-2">{{ $t("time_horizon_mapping_help") }}</small>
          <div v-for="(mapping, mIdx) in settings.prompt_time_horizons" :key="`pth-${mIdx}`" class="mb-3 border rounded p-3">
            <div class="row g-2 align-items-center">
              <div class="col-md-7">
                <label class="form-label">{{ $t("prompt_category") }}</label>
                <select class="form-select" v-model="mapping.class">
                  <option value="">{{ $t("select_prompt_category") }}</option>
                  <option v-for="opt in settings.prompt_classification" :key="`pth-opt-${opt}`" :value="opt">
                    {{ opt }}
                  </option>
                </select>
              </div>
              <div class="col-md-4">
                <label class="form-label">{{ $t("time_horizon") }}</label>
                <select class="form-select" v-model="mapping.horizon">
                  <option v-for="hz in settings.time_horizons" :key="`pth-hz-${hz.key}`" :value="hz.key">
                    {{ hz.label }}
                  </option>
                </select>
              </div>
              <div class="col-md-1 text-end">
                <button type="button" class="btn btn-outline-danger" @click="removePromptMapping(mIdx)">
                  <i class="bi bi-x-lg"></i>
                </button>
              </div>
            </div>
          </div>
          <button type="button" class="btn btn-outline-primary mt-2" @click="addPromptMapping">
            <i class="bi bi-plus-lg"></i> {{ $t("add_prompt_mapping") }}
          </button>
        </div>

        <!-- RAG document time horizon mapping -->
        <div class="mb-4">
          <label class="form-label">{{ $t("rag_time_horizon_mapping") }}</label>
          <small class="form-text text-muted d-block mb-2">{{ $t("rag_time_horizon_mapping_help") }}</small>
          <div v-for="(mapping, mIdx) in settings.rag_time_horizons" :key="`rth-${mIdx}`" class="mb-3 border rounded p-3">
            <div class="row g-2 align-items-center">
              <div class="col-md-7">
                <label class="form-label">{{ $t("rag_category") }}</label>
                <select class="form-select" v-model="mapping.class">
                  <option value="">{{ $t("select_rag_category") }}</option>
                  <option v-for="opt in settings.rag_document_taxonomy" :key="`rth-opt-${opt}`" :value="opt">
                    {{ opt }}
                  </option>
                </select>
              </div>
              <div class="col-md-4">
                <label class="form-label">{{ $t("time_horizon") }}</label>
                <select class="form-select" v-model="mapping.horizon">
                  <option v-for="hz in settings.time_horizons" :key="`rth-hz-${hz.key}`" :value="hz.key">
                    {{ hz.label }}
                  </option>
                </select>
              </div>
              <div class="col-md-1 text-end">
                <button type="button" class="btn btn-outline-danger" @click="removeRagMapping(mIdx)">
                  <i class="bi bi-x-lg"></i>
                </button>
              </div>
            </div>
          </div>
          <button type="button" class="btn btn-outline-primary mt-2" @click="addRagMapping">
            <i class="bi bi-plus-lg"></i> {{ $t("add_rag_mapping") }}
          </button>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("system_prompts") }}</label>
          <div v-for="(item, index) in settings.system_prompts" :key="index" class="mb-3 border rounded p-3">
            <div class="mb-2">
              <input type="text" class="form-control" v-model="item.task" :placeholder="$t('task_name')" />
            </div>
            <div class="mb-2">
              <input type="text" class="form-control" v-model="item.description"
                :placeholder="$t('task_description')" />
            </div>
            <div>
              <textarea class="form-control" v-model="item.prompt" :placeholder="$t('task_prompt')" rows="3"></textarea>
            </div>
            <button type="button" class="btn btn-outline-danger mt-2" @click="removeValue('system_prompts', index)">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <br />
          <button type="button" class="btn btn-outline-primary mt-2" @click="addValue('system_prompts')">
            <i class="bi bi-plus-lg"></i>
          </button>
        </div>

        <div class="mb-3">
          <label class="form-label">{{ $t("predefined_prompts") }}</label>

          <div v-for="(item, index) in settings.predefined_prompts" :key="index" class="mb-3 border rounded p-3">
            <div class="mb-2">
              <input type="text" class="form-control" v-model="item.name" :placeholder="$t('prompt_name')" />
            </div>
            <div>
              <textarea class="form-control" v-model="item.text" :placeholder="$t('prompt_text')" rows="3"></textarea>
            </div>
            <button type="button" class="btn btn-outline-danger mt-2" @click="removeValue('predefined_prompts', index)">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>

          <br />
          <button type="button" class="btn btn-outline-primary mt-2" @click="addValue('predefined_prompts')">
            <i class="bi bi-plus-lg"></i>
          </button>
        </div>

        <div class="d-flex gap-2">
          <button class="btn btn-secondary" type="button" @click="cancel">
            <i class="bi bi-arrow-left"></i>
          </button>
          <button class="btn btn-success" type="submit" @click="submit">
            <i class="bi bi-save"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useStore } from "vuex";

const route = useRoute();
const router = useRouter();
const store = useStore();

const id = route.params.id;
const isEdit = computed(() => id !== "new");

const normalizePredefined = (arr) =>
  Array.isArray(arr)
    ? arr.map(p =>
      typeof p === "string" ? { name: p, text: "" } : { name: p?.name ?? "", text: p?.text ?? "" }
    )
    : [];

const normalizeSystemPrompts = (arr) =>
  Array.isArray(arr)
    ? arr.map(i => ({ task: i?.task ?? "", description: i?.description ?? "", prompt: i?.prompt ?? "" }))
    : [];

const settings = reactive({
  global_system_prompt: "",
  whatsapp_error_message: "",
  memory_generation_prompt: "",
  reminder_inactive_hours: 24, // default value
  // LightRAG Configuration
  lightrag_chunk_token_size: 800,
  lightrag_chunk_overlap_size: 100,
  lightrag_entity_extract_max_gleaning: 1,
  lightrag_query_top_k: 60,
  lightrag_query_max_tokens: 30000,
  lightrag_max_async_llm: 4,
  lightrag_max_async_embedding: 16,
  lightrag_embedding_batch_size: 32,
  lightrag_max_parallel_insert: 4,
  prompt_classification: [],
  response_classification: [],
  interaction_tone_classification: [],
  rag_document_taxonomy: [],
  radar_axes: [],
  time_horizons: [
    { key: "short_term", label: "Short term" },
    { key: "mid_term", label: "Mid term" },
    { key: "long_term", label: "Long term" },
  ],
  prompt_time_horizons: [],
  rag_time_horizons: [],
  system_prompts: [],
  predefined_prompts: [],
});

const normalizeAxisArray = (arr) =>
  Array.isArray(arr)
    ? arr.map((axis) => ({
        name: axis?.name || axis?.axis || "",
        prompt_classes: Array.isArray(axis?.prompt_classes)
          ? axis.prompt_classes.map((v) => v || "")
          : [],
        rag_classes: Array.isArray(axis?.rag_classes)
          ? axis.rag_classes.map((v) => v || "")
          : [],
      }))
    : [];

const defaultHorizonDefs = [
  { key: "short_term", label: "Short term" },
  { key: "mid_term", label: "Mid term" },
  { key: "long_term", label: "Long term" },
];

const normalizeHorizons = (arr) => {
  const byKey = new Map();
  (Array.isArray(arr) ? arr : defaultHorizonDefs).forEach((h) => {
    const key = (h?.key || "").toString().toLowerCase().trim();
    const label = h?.label || h?.name || h?.text || h?.key || "";
    if (!key) return;
    if (!byKey.has(key)) {
      byKey.set(key, { key, label: label || key });
    }
  });
  defaultHorizonDefs.forEach((h) => {
    if (!byKey.has(h.key)) {
      byKey.set(h.key, { ...h });
    }
  });
  return Array.from(byKey.values());
};

const normalizeHorizonKey = (value) => {
  const norm = (value || "").toString().toLowerCase().trim();
  return norm || "short_term";
};

const normalizeHorizonMappings = (arr) =>
  Array.isArray(arr)
    ? arr.map((item) => ({
        class: item?.class || item?.prompt_class || item?.rag_class || "",
        horizon: normalizeHorizonKey(item?.horizon || item?.time_horizon || item?.timeframe || item?.bucket),
      }))
    : [];

const ensureDefaults = (data) => ({
  global_system_prompt: data?.global_system_prompt || "",
  whatsapp_error_message: data?.whatsapp_error_message || "",
  memory_generation_prompt: data?.memory_generation_prompt || "",
  reminder_inactive_hours: data?.reminder_inactive_hours ?? 24,
  // LightRAG Configuration defaults
  lightrag_chunk_token_size: data?.lightrag_chunk_token_size ?? 800,
  lightrag_chunk_overlap_size: data?.lightrag_chunk_overlap_size ?? 100,
  lightrag_entity_extract_max_gleaning: data?.lightrag_entity_extract_max_gleaning ?? 1,
  lightrag_query_top_k: data?.lightrag_query_top_k ?? 60,
  lightrag_query_max_tokens: data?.lightrag_query_max_tokens ?? 30000,
  lightrag_max_async_llm: data?.lightrag_max_async_llm ?? 4,
  lightrag_max_async_embedding: data?.lightrag_max_async_embedding ?? 16,
  lightrag_embedding_batch_size: data?.lightrag_embedding_batch_size ?? 32,
  lightrag_max_parallel_insert: data?.lightrag_max_parallel_insert ?? 4,
  prompt_classification: data?.prompt_classification || [],
  response_classification: data?.response_classification || [],
  interaction_tone_classification: data?.interaction_tone_classification || [],
  rag_document_taxonomy: data?.rag_document_taxonomy || [],
  radar_axes: normalizeAxisArray(data?.radar_axes || data?.analytics?.radar_axes),
  time_horizons: normalizeHorizons(data?.time_horizons || data?.analytics?.time_horizons),
  prompt_time_horizons: normalizeHorizonMappings(data?.prompt_time_horizons || data?.analytics?.prompt_time_horizons),
  rag_time_horizons: normalizeHorizonMappings(data?.rag_time_horizons || data?.analytics?.rag_time_horizons),
  system_prompts: normalizeSystemPrompts(data?.system_prompts),
  predefined_prompts: normalizePredefined(data?.predefined_prompts),
});

const loadSettings = async () => {
  await store.dispatch("admin/loadSettings");
  const data = store.state.admin.settings;

  if (data && Object.keys(data).length > 0) {
    Object.assign(settings, ensureDefaults(data));
  }
};

const addValue = (field) => {
  if (field === "system_prompts") {
    settings.system_prompts.push({ task: "", description: "", prompt: "" });
  } else if (field === "predefined_prompts") {
    settings.predefined_prompts.push({ name: "", text: "" });
  } else {
    settings[field].push("");
  }
};

const removeValue = (field, index) => {
  settings[field].splice(index, 1);
};

const addAxis = () => {
  settings.radar_axes.push({
    name: "",
    prompt_classes: [],
    rag_classes: [],
  });
};

const removeAxis = (index) => {
  settings.radar_axes.splice(index, 1);
};

const addPromptMapping = () => {
  const defaultHorizon = settings.time_horizons?.[0]?.key || "short_term";
  settings.prompt_time_horizons.push({ class: "", horizon: defaultHorizon });
};

const removePromptMapping = (idx) => {
  settings.prompt_time_horizons.splice(idx, 1);
};

const addRagMapping = () => {
  const defaultHorizon = settings.time_horizons?.[0]?.key || "short_term";
  settings.rag_time_horizons.push({ class: "", horizon: defaultHorizon });
};

const removeRagMapping = (idx) => {
  settings.rag_time_horizons.splice(idx, 1);
};

const submit = async () => {
  const payload = JSON.parse(JSON.stringify(settings));
  payload.system_prompts = normalizeSystemPrompts(payload.system_prompts);
  payload.predefined_prompts = normalizePredefined(payload.predefined_prompts)
    .filter(p => p.name || p.text); // optional: drop empty rows
  payload.time_horizons = normalizeHorizons(payload.time_horizons);
  payload.prompt_time_horizons = normalizeHorizonMappings(payload.prompt_time_horizons).filter((m) => m.class);
  payload.rag_time_horizons = normalizeHorizonMappings(payload.rag_time_horizons).filter((m) => m.class);
  await store.dispatch("admin/saveSettings", payload);
  router.push({ name: "Home" });
};

const cancel = () => {
  router.push({ name: "Home" });
};

onMounted(() => {
  loadSettings();
});
</script>
