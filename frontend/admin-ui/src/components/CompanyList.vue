<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h2>{{ $t('companies') }}</h2>
      <button v-if="showCreateCompany" class="btn btn-success" @click="goToCreate">
        <i class="bi bi-plus-lg"></i>
      </button>
    </div>

    <table class="table table-striped">
      <thead>
        <tr>
          <th>{{ $t('name') }}</th>
          <th>{{ $t('industry') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="company in companies" :key="company._id?.$oid || company._id">
          <td>
              <i v-if="company.environment === 'production'" class="bi bi-building"></i>
              <i v-else-if="company.environment === 'course'" class="bi bi-mortarboard"></i>
              <i v-else class="bi bi-code-square"></i>
              &nbsp;
            <a href="#" @click.prevent="openCompany(company)">
              {{ company.name }}
            </a>
          </td>
          <td>{{ company.basic_info?.industry }}</td>
          <!--
          <td>
            <button class="btn btn-sm btn-primary me-2" @click="editCompany(company)">Edit</button>
            <button class="btn btn-sm btn-danger" @click="removeCompany(company._id?.$oid || company._id)">Delete</button>
          </td>
          -->
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { onMounted, computed } from 'vue'
import { useStore } from 'vuex'
import { useRouter } from 'vue-router'
import { decodeJwt } from '../utils/jwt'

const store = useStore()
const router = useRouter()

const companies = computed(() => store.state.admin.companies)

const showCreateCompany = computed(() => {
  const token = store.state.admin.authToken || localStorage.getItem('authToken')
  const claims = decodeJwt(token)
  return claims?.role === 'admin' && claims?.exp > Date.now() / 1000
})

const fetchCompanies = async () => {
  await store.dispatch('admin/loadCompanies')
}

const openCompany = (company) => {
  const id = company._id?.$oid || company._id
  router.push({ name: 'CompanyDetails', params: { id } })
}

const editCompany = (company) => {
  const id = company._id?.$oid || company._id
  router.push({ name: 'EditCompany', params: { id } })
}

const removeCompany = async (id) => {
  if (confirm('Are you sure you want to delete this company?')) {
    await store.dispatch('admin/removeCompany', id)
  }
}

const goToCreate = () => {
  router.push({ name: 'EditCompany', params: { id: 'new' } })
}

onMounted(fetchCompanies)
</script>
