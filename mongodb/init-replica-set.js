// MongoDB replica set initialization script
// This script initializes a single-node replica set required for mongot

try {
  // Check if replica set is already initialized
  var status = rs.status();
  print("Replica set already initialized");
} catch (e) {
  if (e.message.includes("no replset config has been received")) {
    // Initialize the replica set
    print("Initializing replica set 'rs0'...");

    var config = {
      _id: "rs0",
      members: [
        {
          _id: 0,
          host: "mongo:27017",
          priority: 1,
        },
      ],
    };

    var result = rs.initiate(config);

    if (result.ok === 1) {
      print("Replica set initialized successfully");

      // Wait for the replica set to become ready
      var attempts = 0;
      var maxAttempts = 30;

      while (attempts < maxAttempts) {
        try {
          var status = rs.status();
          if (status.myState === 1) {
            // PRIMARY
            print("Replica set is ready and this node is PRIMARY");
            break;
          }
          print("Waiting for replica set to be ready... (attempt " + (attempts + 1) + "/" + maxAttempts + ")");
          sleep(1000); // Wait 1 second
          attempts++;
        } catch (waitError) {
          print("Still waiting for replica set initialization...");
          sleep(1000);
          attempts++;
        }
      }

      if (attempts >= maxAttempts) {
        print("Warning: Replica set initialization may still be in progress");
      }
    } else {
      print("Failed to initialize replica set: " + JSON.stringify(result));
    }
  } else {
    print("Unexpected error checking replica set status: " + e.message);
  }
}
