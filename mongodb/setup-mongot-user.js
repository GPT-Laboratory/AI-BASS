// MongoDB user and database setup for mongot
// This script creates necessary users and databases for the mongot service
// Moved from init_mongot_and_vector.py

// Setup for admin database
var adminDb = db.getSiblingDB("admin");
const password = process.env.MONGOT_PASSWORD;
if (!password) throw new Error("MONGOT_PASSWORD is required");
var existingUser = adminDb.getUser("mongotUser");

if (existingUser) {
  adminDb.updateUser("mongotUser", { pwd: password });
} else {
  print("Creating mongotUser...");
  try {
    adminDb.createUser({
      user: "mongotUser",
      pwd: password,
      roles: [{ role: "searchCoordinator", db: "admin" }],
    });
    print("User mongotUser created successfully");
  } catch (e) {
    throw e;
  }
}

print("MongoDB setup completed successfully");
