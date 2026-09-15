"""Logistics domain implementation for AoT+ demonstration."""
from typing import Dict, List, Set, Tuple, Optional

class LogisticsState:
    """Representation of a state in the Logistics domain."""
    
    def __init__(self):
        """Initialize a LogisticsState."""
        # Maps package names to their locations (city, vehicle, or location within city)
        self.package_locations = {}
        # Maps vehicle names to their locations (city or location within city)
        self.vehicle_locations = {}
        # Maps city names to the locations within them
        self.city_locations = {}
        
    def add_city(self, city: str, locations: List[str]):
        """Add a city with its locations.
        
        Args:
            city: Name of the city
            locations: List of location names within the city
        """
        self.city_locations[city] = locations
        
    def add_vehicle(self, vehicle: str, location: str):
        """Add a vehicle at a location.
        
        Args:
            vehicle: Name of the vehicle
            location: Location of the vehicle (city or location within a city)
        """
        self.vehicle_locations[vehicle] = location
        
    def add_package(self, package: str, location: str):
        """Add a package at a location.
        
        Args:
            package: Name of the package
            location: Location of the package (city, vehicle, or location within a city)
        """
        self.package_locations[package] = location
        
    def load_package(self, package: str, vehicle: str) -> bool:
        """Load a package onto a vehicle.
        
        Args:
            package: Name of the package to load
            vehicle: Name of the vehicle to load the package onto
            
        Returns:
            True if the action was valid and performed, False otherwise
        """
        # Check if package and vehicle exist
        if package not in self.package_locations or vehicle not in self.vehicle_locations:
            return False
            
        # Check if package and vehicle are at the same location
        package_loc = self.package_locations[package]
        vehicle_loc = self.vehicle_locations[vehicle]
        
        if package_loc != vehicle_loc:
            return False
            
        # Update package location
        self.package_locations[package] = vehicle
        return True
        
    def unload_package(self, package: str, location: str) -> bool:
        """Unload a package from a vehicle to a location.
        
        Args:
            package: Name of the package to unload
            location: Location to unload the package at
            
        Returns:
            True if the action was valid and performed, False otherwise
        """
        # Check if package exists and is on a vehicle
        if package not in self.package_locations:
            return False
            
        package_loc = self.package_locations[package]
        
        # Check if package is on a vehicle
        if package_loc not in self.vehicle_locations:
            return False
            
        # Check if vehicle is at the specified location
        vehicle = package_loc
        vehicle_loc = self.vehicle_locations[vehicle]
        
        if vehicle_loc != location:
            return False
            
        # Update package location
        self.package_locations[package] = location
        return True
        
    def drive_vehicle(self, vehicle: str, destination: str) -> bool:
        """Drive a vehicle to a destination within the same city.
        
        Args:
            vehicle: Name of the vehicle to drive
            destination: Destination location within the city
            
        Returns:
            True if the action was valid and performed, False otherwise
        """
        # Check if vehicle exists
        if vehicle not in self.vehicle_locations:
            return False
            
        vehicle_loc = self.vehicle_locations[vehicle]
        
        # Find the city of the vehicle
        vehicle_city = None
        for city, locations in self.city_locations.items():
            if vehicle_loc in locations:
                vehicle_city = city
                break
                
        # Check if destination is in the same city
        if vehicle_city is None or destination not in self.city_locations[vehicle_city]:
            return False
            
        # Update vehicle location
        self.vehicle_locations[vehicle] = destination
        return True
        
    def fly_airplane(self, airplane: str, destination: str) -> bool:
        """Fly an airplane to a destination city.
        
        Args:
            airplane: Name of the airplane to fly
            destination: Destination city
            
        Returns:
            True if the action was valid and performed, False otherwise
        """
        # Check if airplane exists
        if airplane not in self.vehicle_locations:
            return False
            
        # Check if destination is a city
        if destination not in self.city_locations:
            return False
            
        # Airplanes can only be in cities (airports)
        if self.vehicle_locations[airplane] not in self.city_locations:
            return False
            
        # Update airplane location
        self.vehicle_locations[airplane] = destination
        return True
        
    def __str__(self) -> str:
        """Convert the state to a readable string representation.
        
        Returns:
            String representation of the state
        """
        result = []
        
        # Add package locations
        for package, location in self.package_locations.items():
            result.append(f"Package {package} is at {location}")
            
        # Add vehicle locations
        for vehicle, location in self.vehicle_locations.items():
            result.append(f"Vehicle {vehicle} is at {location}")
            
        return ", ".join(result)
    
    def is_goal_state(self, goal_state: 'LogisticsState') -> bool:
        """Check if this state matches the goal state.
        
        Args:
            goal_state: The goal state to compare against
            
        Returns:
            True if this state matches the goal state, False otherwise
        """
        # For Logistics, we typically only care about package locations in the goal state
        for package, location in goal_state.package_locations.items():
            if package not in self.package_locations or self.package_locations[package] != location:
                return False
                
        return True


class LogisticsDomain:
    """Implementation of the Logistics planning domain."""
    
    @staticmethod
    def get_domain_description() -> str:
        """Get the description of the Logistics domain for the prompt.
        
        Returns:
            Domain description string
        """
        return """
# Logistics Planning Domain

## Description:
The Logistics domain involves the transportation of packages between locations using trucks and airplanes.
The world consists of cities, each containing a set of locations (including an airport).
Trucks can move packages within a city, and airplanes can move packages between cities.

## Rules:
1. Packages can be loaded onto a vehicle only if the package and vehicle are at the same location.
2. Packages can be unloaded from a vehicle only at the vehicle's current location.
3. Trucks can drive between locations within the same city.
4. Airplanes can fly between airports in different cities.
5. The goal is to deliver packages to their destination locations.

## Actions:
- Load a package onto a vehicle
- Unload a package from a vehicle
- Drive a truck between locations within a city
- Fly an airplane between cities

## Action Format:
- Load package P onto vehicle V
- Unload package P from vehicle V at location L
- Drive truck T from location L1 to location L2
- Fly airplane A from city C1 to city C2

## State Representation:
The state is represented by describing where each package and vehicle is located.
For example: "Package P1 is at location L1, Truck T1 is at location L2, Airplane A1 is at city C1"
"""

    @staticmethod
    def parse_state_description(description: str) -> LogisticsState:
        """Parse a natural language description of a Logistics state.
        
        Args:
            description: Natural language description of the state
            
        Returns:
            LogisticsState object representing the described state
        """
        state = LogisticsState()
        
        # Add some default cities and locations for parsing
        state.add_city("City1", ["Airport1", "Location1", "Location2"])
        state.add_city("City2", ["Airport2", "Location3", "Location4"])
        
        # Extract package locations
        import re
        package_pattern = r"Package ([A-Za-z0-9]+) is at ([A-Za-z0-9]+)"
        for match in re.finditer(package_pattern, description):
            package = match.group(1)
            location = match.group(2)
            state.add_package(package, location)
            
        # Extract vehicle locations
        vehicle_pattern = r"(Truck|Airplane) ([A-Za-z0-9]+) is at ([A-Za-z0-9]+)"
        for match in re.finditer(vehicle_pattern, description):
            vehicle_type = match.group(1)
            vehicle = match.group(2)
            location = match.group(3)
            state.add_vehicle(vehicle, location)
            
        return state
    
    @staticmethod
    def generate_example_problem() -> Tuple[str, str, List[str], List[List[str]]]:
        """Generate an example Logistics problem with solution and random trajectories.
        
        Returns:
            Tuple of (initial_state_description, goal_state_description, 
                     solution_trajectory, random_trajectories)
        """
        initial_state = ("Package P1 is at Location1, Package P2 is at Location3, "
                        "Truck T1 is at Location2, Truck T2 is at Location4, "
                        "Airplane A1 is at Airport1")
                        
        goal_state = ("Package P1 is at Location4, Package P2 is at Location2")
        
        solution = [
            "Drive Truck T1 from Location2 to Location1",
            "Load Package P1 onto Truck T1",
            "Drive Truck T1 from Location1 to Airport1",
            "Unload Package P1 from Truck T1 at Airport1",
            "Load Package P1 onto Airplane A1",
            "Fly Airplane A1 from Airport1 to Airport2",
            "Unload Package P1 from Airplane A1 at Airport2",
            "Drive Truck T2 from Location4 to Airport2",
            "Load Package P1 onto Truck T2",
            "Drive Truck T2 from Airport2 to Location4",
            "Unload Package P1 from Truck T2 at Location4",
            "Drive Truck T2 from Location4 to Location3",
            "Load Package P2 onto Truck T2",
            "Drive Truck T2 from Location3 to Airport2",
            "Unload Package P2 from Truck T2 at Airport2",
            "Load Package P2 onto Airplane A1",
            "Fly Airplane A1 from Airport2 to Airport1",
            "Unload Package P2 from Airplane A1 at Airport1",
            "Drive Truck T1 from Airport1 to Location2",
            "Load Package P2 onto Truck T1",
            "Unload Package P2 from Truck T1 at Location2"
        ]
        
        random_trajectory1 = [
            "Drive Truck T1 from Location2 to Airport1",
            "Fly Airplane A1 from Airport1 to Airport2",
            "Drive Truck T2 from Location4 to Airport2"
        ]
        
        random_trajectory2 = [
            "Drive Truck T1 from Location2 to Location1",
            "Load Package P1 onto Truck T1",
            "Drive Truck T1 from Location1 to Location2",
            "Unload Package P1 from Truck T1 at Location2"
        ]
        
        return initial_state, goal_state, solution, [random_trajectory1, random_trajectory2] 