<template>
  <div v-if="company">
    <!-- Error Alert -->
    <div v-if="error" class="alert alert-danger alert-dismissible fade show mb-3" role="alert">
      <i class="bi bi-exclamation-triangle"></i>
      {{ error }}
      <button type="button" class="btn-close" @click="clearError"></button>
    </div>

    <h2>{{ company.name }} {{ $t("metadata") }}</h2>
    <div class="card mt-4">
      <div class="card-body">
        <h5 class="card-title">
          <span v-if="isEdit">
            {{ $t("edit_metadata") }}
          </span>
          <span v-else>
            {{ $t("add_metadata") }}
          </span>
        </h5>

        <div class="mb-3">
          <label for="type" class="form-label">{{ $t("type") }}</label>
          <select id="type" v-model="metadata.type" class="form-select" :disabled="isEdit" required>
            <option disabled value="">{{ $t("select_a_type") }}</option>
            <option value="strategy">{{ $t("strategy") }}</option>
            <option value="personnel">{{ $t("personnel") }}</option>
            <option value="long_term_goals">{{ $t("long_term_goals") }}</option>
            <option value="business_environment">{{ $t("business_environment") }}</option>
            <!-- Show these options when editing existing metadata of these types -->
            <option v-if="isEdit && metadata.type === 'google_drive_file'" value="google_drive_file">{{ $t("google_drive_file") }}</option>
            <option v-if="isEdit && metadata.type === 'onedrive_file'" value="onedrive_file">{{ $t("onedrive_file") }}</option>
            <option v-if="isEdit && metadata.type === 'manual_upload_file'" value="manual_upload_file">{{ $t("manual_upload_file") }}</option>
            <option v-if="isEdit && metadata.type === 'email'" value="email">{{ $t("email") }}</option>
            <option v-if="isEdit && metadata.type === 'ai_generated_memory'" value="ai_generated_memory">{{ $t("ai_generated_memory") || "AI-generoitu muisti" }}</option>
            <option value="other">{{ $t("other") }}</option>
          </select>
        </div>

        <div class="mb-3" v-if="metadata.content">
          <label for="description" class="form-label">{{ $t("description") }}</label>
          <textarea id="description" v-model="descriptionValue" class="form-control" rows="4" required />
        </div>

        <div class="mb-3">
          <label for="company_id" class="form-label">{{ $t("company_id") }}</label>
          <input disabled type="text" id="company_id" v-model="metadata.company_id" class="form-control" required />
        </div>

        <div class="mb-3">
          <label for="updated_at" class="form-label">{{ $t("updated") }}</label>
          <input disabled type="text" id="updated_at" v-model="metadata.updated_at" class="form-control" required />
        </div>

        <div class="d-flex gap-2">
          <button class="btn btn-danger" type="button" @click="deleteMetadata" v-if="isEdit">
            <i class="bi bi-x-lg"></i>
          </button>
          <button class="btn btn-secondary" type="button" @click="router.push({ name: 'CompanyDetails', params: { id: companyId } })">
            <i class="bi bi-arrow-left"></i>
          </button>
          <button class="btn btn-success" type="button" @click="saveMetadata">
            <i class="bi bi-save"></i>
          </button>
        </div>
      </div>
    </div>
  </div>

  <div v-else>
    <p>{{ $t("loading_company_details") }}</p>
  </div>
</template>

<script setup>
import { onMounted, computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useStore } from "vuex";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const store = useStore();

const companyId = route.params.companyId;
const isEdit = computed(() => route.params.metadataId !== "new");

// Company state
const company = computed(() => store.state.admin.selectedCompany);
const error = computed(() => store.state.admin.error);

// Reactive metadata object
const metadata = ref({
  type: "",
  content: {
    description: "",
  },
  company_id: companyId,
  updated_at: new Date().toISOString(),
});

// Computed property for description that tries 'description' first, then 'full_content'
const descriptionValue = computed({
  get() {
    return metadata.value.content?.description || metadata.value.content?.full_content || metadata.value.content?.body_text || "";
  },
  set(value) {
    if (!metadata.value.content) {
      metadata.value.content = {};
    }
    // Try to preserve the original field name
    if (metadata.value.content.hasOwnProperty("full_content")) {
      metadata.value.content.full_content = value;
    } else if (metadata.value.content.hasOwnProperty("body_text")) {
      metadata.value.content.body_text = value;
    } else {
      metadata.value.content.description = value;
    }
  },
});

const fetchCompany = async () => {
  await store.dispatch("admin/loadCompany", companyId);
};

const fetchMetadata = async (id) => {
  if (id) {
    await store.dispatch("admin/loadMetadataById", id);
    const fetched = store.state.admin.selectedMetadata;

    metadata.value = {
      id: fetched._id.$oid,
      type: fetched.type,
      content: { ...fetched.content },
      company_id: fetched.company_id,
      updated_at: new Date().toISOString(),
    };
  }
};

const saveMetadata = async () => {
  try {
    if (isEdit.value) {
      const id = route.params.metadataId;
      if (!id) throw new Error("Missing metadata ID in route parameters.");
      await store.dispatch("admin/editMetadata", {
        id,
        data: metadata.value,
      });
    } else {
      await store.dispatch("admin/addMetadata", metadata.value);
    }
    router.push({ name: "CompanyDetails", params: { id: companyId } });
  } catch (error) {
    console.error("[saveMetadata] Failed to save metadata:", error);
  }
};

const deleteMetadata = async () => {
  const confirmed = confirm(t("are_you_sure"));
  if (!confirmed) return;

  try {
    await store.dispatch("admin/removeMetadata", {
      id: metadata.value.id,
      company_id: companyId,
    });

    router.push({ name: "CompanyDetails", params: { id: companyId } });
  } catch (error) {
    console.error("[deleteMetadata] Failed to delete metadata:", error);
    // Error handling is now done through the store's error state
  }
};

const clearError = () => {
  store.commit("admin/SET_ERROR", null);
};

onMounted(async () => {
  await fetchCompany();
  if (isEdit.value) {
    await fetchMetadata(route.params.metadataId);
  }
});
</script>
