<template>
  <div v-if="true">
    <!-- Error Alert -->
    <div v-if="error" class="alert alert-danger alert-dismissible fade show mb-3" role="alert">
      <i class="bi bi-exclamation-triangle"></i>
      {{ error }}
      <button type="button" class="btn-close" @click="clearError"></button>
    </div>

    <h2>{{ isEdit ? $t("edit_company") : $t("add_company") }}</h2>

    <div class="card mt-4">
      <div class="card-body">
        <h5 class="card-title">
          <span v-if="isEdit">{{ $t("edit_company") }}</span>
          <span v-else>{{ $t("add_company") }}</span>
        </h5>

        <div class="mb-3">
          <label class="form-label" for="name">{{ $t("company_name") }}</label>
          <input id="name" class="form-control" v-model="form.name" required />
        </div>

        <div class="mb-3">
          <label class="form-label" for="email">{{ $t("email") }}</label>
          <input id="email" class="form-control" v-model="form.basic_info.email" />
        </div>

        <div class="mb-3">
          <label class="form-label" for="business_id">{{ $t("business_id") }}</label>
          <input id="business_id" class="form-control" v-model="form.business_id" required />
        </div>

        <div class="mb-3">
          <label class="form-label" for="industry">{{ $t("industry") }}</label>
          <input id="industry" class="form-control" v-model="form.basic_info.industry" />
        </div>

        <div class="mb-3">
          <label class="form-label" for="founded">{{ $t("founded") }}</label>
          <input id="founded" class="form-control" v-model="form.basic_info.founded" />
        </div>

        <div class="mb-3">
          <label class="form-label" for="headquarters">{{ $t("headquarters") }}</label>
          <input id="headquarters" class="form-control" v-model="form.basic_info.headquarters" />
        </div>

        <div class="mb-3">
          <label class="form-label" for="environment">{{ $t("environment") }}</label>
          <select id="environment" class="form-select" v-model="form.environment">
            <option value="production">{{ $t("production") }}</option>
            <option value="course">{{ $t("course") }}</option>
            <option value="development">{{ $t("development") }}</option>
          </select>
        </div>

        <!--<div class="mb-3">
          <label class="form-label">{{ $t('phone_numbers') }}</label>

          <div v-for="(number, index) in form.phone_numbers" :key="index" class="input-group mb-2">
            <input type="text" class="form-control" v-model="form.phone_numbers[index]"
              :placeholder="$t('enter_phone_number')" />
            <button type="button" class="btn btn-outline-danger" @click="removePhoneNumber(index)">
              {{ $t('remove') }}
            </button>
          </div>
          <br>
          <button type="button" class="btn btn-outline-primary mt-2" @click="addPhoneNumber">
            {{ $t('add_phone_number') }}
          </button>
        </div>-->

        <div class="d-flex gap-2">
          <button class="btn btn-danger" type="button" @click="deleteCompany" v-if="isEdit">
            <i class="bi bi-x-lg"></i>
          </button>
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
import { ref, reactive, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useStore } from "vuex";
import { useI18n } from "vue-i18n";

const route = useRoute();
const router = useRouter();
const store = useStore();
const { t } = useI18n();

const id = route.params.id;
const isEdit = computed(() => id !== "new");
const error = computed(() => store.state.admin.error);

const form = reactive({
  name: "",
  business_id: "",
  environment: "development", // default
  basic_info: {
    industry: "",
    email: "",
    founded: "",
    headquarters: "",
  },
  //phone_numbers: [],
});

const addPhoneNumber = () => {
  form.phone_numbers.push("");
};

const removePhoneNumber = (index) => {
  form.phone_numbers.splice(index, 1);
};

const loadCompany = async () => {
  await store.dispatch("admin/loadCompany", id);
  const data = store.state.admin.selectedCompany;

  if (data) {
    Object.assign(form, {
      name: data.name || "",
      business_id: data.business_id || "",
      environment: data.environment || "development",
      basic_info: {
        industry: data.basic_info?.industry || "",
        email: data.basic_info?.email || "",
        founded: data.basic_info?.founded || "",
        headquarters: data.basic_info?.headquarters || "",
      },
    });
  }
};

const submit = async () => {
  const payload = JSON.parse(JSON.stringify(form));

  if (isEdit.value) {
    await store.dispatch("admin/editCompany", { id, data: payload });
  } else {
    await store.dispatch("admin/addCompany", payload);
  }
  if (isEdit.value) {
    router.push({ name: "CompanyDetails", params: { id: id } });
  } else {
    router.push({ name: "Home" });
  }
};

const deleteCompany = async () => {
  const confirmed = confirm(t("are_you_sure"));
  if (!confirmed) return;

  try {
    await store.dispatch("admin/removeCompany", id);

    router.push({ name: "Home", params: {} });
  } catch (error) {
    console.error("[deleteMetadata] Failed to delete company:", error);
    // Error handling is now done through the store's error state
  }
};

const clearError = () => {
  store.commit("admin/SET_ERROR", null);
};

const cancel = () => {
  router.push({ name: "Home" });
};

onMounted(() => {
  if (isEdit.value) loadCompany();
});
</script>
