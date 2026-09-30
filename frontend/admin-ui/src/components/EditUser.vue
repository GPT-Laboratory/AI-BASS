<template>
  <div v-if="company">
    <!-- Error Alert -->
    <div v-if="error" class="alert alert-danger alert-dismissible fade show mb-3" role="alert">
      <i class="bi bi-exclamation-triangle"></i>
      {{ error }}
      <button type="button" class="btn-close" @click="clearError"></button>
    </div>

    <h2>{{ company.name }} {{ $t("users") }}</h2>
    <div class="card mt-4">
      <div class="card-body">
        <h5 class="card-title">
          <span v-if="isEdit">
            {{ $t("edit_user") }}
          </span>
          <span v-else>
            {{ $t("add_user") }}
          </span>
        </h5>

        <div class="mb-3">
          <label for="first_name" class="form-label">{{ $t("first_name") }}</label>
          <input id="first_name" v-model="user.first_name" type="text" class="form-control" required />
        </div>

        <div class="mb-3">
          <label for="last_name" class="form-label">{{ $t("last_name") }}</label>
          <input id="last_name" v-model="user.last_name" type="text" class="form-control" required />
        </div>

        <div class="mb-3">
          <label for="description" class="form-label">{{ $t("description") }}</label>
          <textarea id="description" v-model="user.description" class="form-control" rows="3" required />
        </div>

        <div class="mb-3">
          <label for="system_prompt" class="form-label">{{ $t("system_prompt") }}</label>
          <textarea id="system_prompt" v-model="user.system_prompt" class="form-control" rows="3" required />
        </div>

        <div class="mb-3">
          <label for="phone_number" class="form-label">{{ $t("phone_number") }}</label>
          <input id="phone_number" v-model="user.phone_number" type="tel" class="form-control" required />
        </div>

        <div class="mb-3">
          <label for="admin_password" class="form-label">{{ $t("admin_password") }}</label>
          <input id="admin_password" v-model="user.admin_password" type="password" class="form-control" required />
        </div>

        <div class="mb-3">
          <label for="company_id" class="form-label">{{ $t("company_id") }}</label>
          <input id="company_id" v-model="user.company_id" type="text" class="form-control" disabled />
        </div>

        <div class="mb-3" v-if="!isEdit">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="send_welcome_message" v-model="user.send_welcome_message" />
            <label class="form-check-label" for="send_welcome_message">
              {{ $t("send_welcome_whatsapp_message") }}
            </label>
          </div>
        </div>

        <div class="d-flex gap-2">
          <button class="btn btn-danger" type="button" @click="deleteUser" v-if="isEdit">
            <i class="bi bi-x-lg"></i>
          </button>
          <button class="btn btn-secondary" type="button" @click="router.push({ name: 'CompanyDetails', params: { id: companyId } })">
            <i class="bi bi-arrow-left"></i>
          </button>
          <button class="btn btn-success" type="button" @click="saveUser">
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
import { ref, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useStore } from "vuex";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const store = useStore();

const companyId = route.params.companyId;
const isEdit = computed(() => route.params.userId !== "new");

const company = computed(() => store.state.admin.selectedCompany);
const error = computed(() => store.state.admin.error);

const user = ref({
  first_name: "",
  last_name: "",
  description: "",
  system_prompt: "",
  phone_number: "",
  admin_password: "",
  company_id: companyId,
  send_welcome_message: false,
});

const fetchCompany = async () => {
  await store.dispatch("admin/loadCompany", companyId);
};

const fetchUser = async (id) => {
  if (id) {
    await store.dispatch("admin/loadUserById", id);
    const fetched = store.state.admin.selectedUser;

    user.value = {
      id: fetched._id?.$oid,
      first_name: fetched.first_name,
      last_name: fetched.last_name,
      description: fetched.description,
      system_prompt: fetched.system_prompt,
      phone_number: fetched.phone_number,
      admin_password: fetched.admin_password,
      company_id: fetched.company_id,
    };
  }
};

const saveUser = async () => {
  try {
    if (isEdit.value) {
      await store.dispatch("admin/editUser", {
        id: user.value.id,
        data: user.value,
      });
    } else {
      await store.dispatch("admin/addUser", user.value);
    }
    router.push({ name: "CompanyDetails", params: { id: companyId } });
  } catch (error) {
    console.error("[saveUser] Failed to save user:", error);
  }
};

const deleteUser = async () => {
  const confirmed = confirm(t("are_you_sure"));
  if (!confirmed) return;

  try {
    await store.dispatch("admin/removeUser", {
      id: user.value.id,
      company_id: companyId,
    });
    router.push({ name: "CompanyDetails", params: { id: companyId } });
  } catch (error) {
    console.error("[deleteUser] Failed to delete user:", error);
    // Error handling is now done through the store's error state
  }
};

const clearError = () => {
  store.commit("admin/SET_ERROR", null);
};

onMounted(async () => {
  await fetchCompany();
  if (isEdit.value) {
    await fetchUser(route.params.userId);
  }
});
</script>
