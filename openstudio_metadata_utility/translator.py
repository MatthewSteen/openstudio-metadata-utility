from rdflib import Namespace

import tasty.constants as tc
import tasty.graphs as tg
import tasty.entities as te

import networkx as nx

from openstudio_metadata_utility.openstudio_graph import OpenStudioGraph
from openstudio_metadata_utility.utilities import MetaNode, MetaRef, name_to_id, cast_openstudio_object, PlantType

import openstudio

h_ont = tg.load_ontology(tc.HAYSTACK, tc.V3_9_10)
b_ont = tg.load_ontology(tc.BRICK, tc.V1_2)

# Specify the schema version (tc.V9_9_10, etc.) to use
hp = te.HaystackPointDefs(tc.V3_9_10)
he = te.HaystackEquipDefs(tc.V3_9_10)
hrefs = te.HaystackRefDefs(tc.V3_9_10)

bp = te.BrickPointDefs(tc.V1_2)
be = te.BrickEquipmentDefs(tc.V1_2)
bz = te.BrickZoneDefs(tc.V1_2)
bl = te.BrickLocationDefs(tc.V1_2)
bs = te.BrickSystemDefs(tc.V1_2)
brefs = te.BrickRefDefs(tc.V1_2)

# Bind all of the first class types as attributes
hp.bind()
he.bind()
hrefs.bind()

bp.bind()
be.bind()
bz.bind()
bl.bind()
bs.bind()
brefs.bind()

# Simple wrapper around all of the shapes
shrap = te.ShapesWrapper(tc.HAYSTACK, tc.V3_9_10)

shrap.bind()
shrap.bind_composite()

equip_ref = MetaRef(hrefs.equipRef, brefs.isPartOf)
point_ref = MetaRef(hrefs.equipRef, brefs.isPointOf)
air_ref = MetaRef(hrefs.airRef, brefs.isFedBy)
space_ref = MetaRef(hrefs.spaceRef, brefs.hasLocation)
zone_point_ref = MetaRef(hrefs.spaceRef, brefs.isPointOf)
site_ref = MetaRef(hrefs.siteRef, brefs.hasLocation)

class Translator:

    def __init__(self, model, building_name) -> None:
        self.model = model
        self.building_name = building_name
        self.namespace = Namespace(f'{building_name}/')
        self.nodes = []
        self.G = None


    def translate(self):
        model = self.model
        self.nodes = []

        self.G = OpenStudioGraph(model)
        hg = tg.get_versioned_graph(tc.HAYSTACK, tc.V3_9_10)
        bg = tg.get_versioned_graph(tc.BRICK, tc.V1_2)

        graphs = {(tc.HAYSTACK, tc.V3_9_10): hg, (tc.BRICK, tc.V1_2): bg}

        hg.bind(self.building_name, self.namespace)
        bg.bind(self.building_name, self.namespace)

        site_object = cast_openstudio_object(model.getObjectsByType(openstudio.IddObjectType('OS:Building'))[0])
        site = self.create_node(shrap.SiteShape, bl.Building, name=self.building_name)#model_object=site_object)
        site.bind_to_graph(hg)
        site.bind_to_graph(bg)

        self.G.set_extra('site', site)

        for node in self.G.get_nodes_by_type(openstudio.IddObjectType('OS:AirloopHVAC')):
            loop_object = self.G.get_object_from_node(node)

            ahu = self.create_node(he.ahu, be.AHU, name=node)
            ahu.add_relationship(site_ref, site)
            outdoor_air_node = loop_object.outdoorAirNode().get()
            mixed_air_node = loop_object.mixedAirNode().get()
            supply_outlet_node = loop_object.supplyOutletNode()
            supply_inlet_node = loop_object.supplyInletNode()
            relief_air_node = loop_object.reliefAirNode().get()

            supply_context = self.G.get_downstream_subgraph(supply_inlet_node, stop_at_nodes=[node], stop_at_types=[openstudio.IddObjectType('OS:Connector:Mixer')])
            supply_context.set_extra('ahu', ahu)
            nx.nx_pydot.to_pydot(supply_context).write_png(f"{node}.png")
            demand_context = self.G.get_downstream_subgraph(loop_object.demandInletNode(), stop_at_nodes=[node])
            demand_context.set_extra('ahu', ahu)

            self.add_sensor(outdoor_air_node, "System Node Temperature", ahu, self.create_node(hp.outside_air_temp_sensor, bp.Outside_Air_Temperature_Sensor), point_ref)
            self.add_sensor(outdoor_air_node, "System Node Relative Humidity", ahu, self.create_node(hp.outside_air_humidity_sensor, bp.Outside_Air_Humidity_Sensor), point_ref)
            oadp = self.create_node(hp.outside_air_temp_sensor, bp.Outside_Air_Dewpoint_Sensor)
            oadp.add_tags(['dewPoint'], h_ont)
            self.add_sensor(outdoor_air_node, "System Node Dewpoint Temperature", ahu, oadp, point_ref)
            self.add_sensor(outdoor_air_node, "System Node Mass Flow Rate", ahu, self.create_node(hp.outside_air_flow_sensor, bp.Outside_Air_Flow_Sensor), point_ref)

            mats = self.create_node(hp.air_temp_sensor, bp.Mixed_Air_Temperature_Sensor)
            mats.add_tags(['mixed'], h_ont)
            marhs = self.create_node(hp.air_humidity_sensor, bp.Mixed_Air_Humidity_Sensor)
            marhs.add_tags(['mixed'], h_ont)
            mafs = self.create_node(hp.air_flow_sensor, bp.Air_Flow_Sensor)
            mafs.add_tags(['mixed'], h_ont)
            self.add_sensor(mixed_air_node, "System Node Temperature", ahu, mats, point_ref)
            self.add_sensor(mixed_air_node, "System Node Relative Humidity", ahu, marhs, point_ref)
            self.add_sensor(mixed_air_node, "System Node Mass Flow Rate", ahu, mafs, point_ref)

            self.add_sensor(supply_outlet_node, "System Node Temperature", ahu, self.create_node(hp.discharge_air_temp_sensor, bp.Discharge_Air_Temperature_Sensor), point_ref)
            self.add_sensor(supply_outlet_node, "System Node Relative Humidity", ahu, self.create_node(hp.discharge_air_humidity_sensor, bp.Discharge_Air_Humidity_Sensor), point_ref)
            self.add_sensor(supply_outlet_node, "System Node Mass Flow Rate", ahu, self.create_node(hp.discharge_air_flow_sensor, bp.Discharge_Air_Flow_Sensor), point_ref)

            self.add_sensor(supply_inlet_node, "System Node Temperature", ahu, self.create_node(hp.return_air_temp_sensor, bp.Return_Air_Temperature_Sensor), point_ref)
            self.add_sensor(supply_inlet_node, "System Node Relative Humidity", ahu, self.create_node(hp.return_air_humidity_sensor, bp.Return_Air_Humidity_Sensor), point_ref)
            self.add_sensor(supply_inlet_node, "System Node Mass Flow Rate", ahu, self.create_node(hp.return_air_flow_sensor, bp.Return_Air_Flow_Sensor), point_ref)

            self.add_sensor(relief_air_node, "System Node Temperature", ahu, self.create_node(hp.exhaust_air_temp_sensor, bp.Exhaust_Air_Temperature_Sensor), point_ref)
            self.add_sensor(relief_air_node, "System Node Relative Humidity", ahu, self.create_node(hp.exhaust_air_humidity_sensor, bp.Exhaust_Air_Humidity_Sensor), point_ref)
            self.add_sensor(relief_air_node, "System Node Mass Flow Rate", ahu, self.create_node(hp.exhaust_air_flow_sensor, bp.Exhaust_Air_Flow_Sensor), point_ref)

            self.resolve_supply_coils(supply_context)
            self.resolve_supply_fans(supply_context)

            for node in supply_context.get_nodes_by_type(openstudio.IddObjectType("OS:HeatExchanger:AirToAir:SensibleAndLatent")):
                heat_wheel = self.create_node(shrap.HeatRecoveryShape, be.Heat_Wheel, name=node)
                heat_wheel.add_relationship(equip_ref, ahu)
                erv_object = supply_context.get_object_from_node(node)
                primary_outlet_object = erv_object.primaryAirOutletModelObject().get()
                secondary_inlet_object = erv_object.secondaryAirInletModelObject().get()

                self.add_sensor(primary_outlet_object, "System Node Temperature", heat_wheel, self.create_node(shrap.HeatRecoveryAirLeavingShape, bp.Outside_Air_Temperature_Sensor), point_ref).add_tags(['temp'], h_ont)
                self.add_sensor(primary_outlet_object, "System Node Relative Humidity", heat_wheel, self.create_node(shrap.HeatRecoveryAirLeavingShape, bp.Outside_Air_Humidity_Sensor), point_ref).add_tags(['humidity'], h_ont)
                self.add_sensor(primary_outlet_object, "System Node Mass Flow Rate", heat_wheel, self.create_node(shrap.HeatRecoveryAirLeavingShape, bp.Outside_Air_Flow_Sensor), point_ref).add_tags(['flow'], h_ont)

                self.add_sensor(secondary_inlet_object, "System Node Temperature", heat_wheel, self.create_node(shrap.HeatRecoveryAirEnteringShape, bp.Exhaust_Air_Temperature_Sensor), point_ref).add_tags(['temp'], h_ont)
                self.add_sensor(secondary_inlet_object, "System Node Relative Humidity", heat_wheel, self.create_node(shrap.HeatRecoveryAirEnteringShape, bp.Exhaust_Air_Humidity_Sensor), point_ref).add_tags(['humidity'], h_ont)
                self.add_sensor(secondary_inlet_object, "System Node Mass Flow Rate", heat_wheel, self.create_node(shrap.HeatRecoveryAirEnteringShape, bp.Exhaust_Air_Flow_Sensor), point_ref).add_tags(['flow'], h_ont)

            zones = demand_context.get_nodes_by_type(openstudio.IddObjectType("OS:ThermalZone"))
            multi_zones = len(zones) > 1
            for node in zones:
                zone_context = demand_context.get_upstream_subgraph(node, stop_at_types=[openstudio.IddObjectType("OS:AirLoopHVAC:ZoneSplitter")])
                zone_object = demand_context.get_object_from_node(node)
                zone_return_object = zone_object.returnAirModelObject().get()
                zone = self.create_node(shrap.HVACZoneShape, bz.HVAC_Zone, name=node)
                zone_context.set_extra('zone', zone)
                zone.add_relationship(hrefs.siteRef, site)

                self.resolve_terminals(zone_context, multi_zones)

                if multi_zones:
                    self.add_sensor(zone_return_object, "System Node Temperature", zone, self.create_node(hp.return_air_temp_sensor, bp.Return_Air_Temperature_Sensor), zone_point_ref)
                    self.add_sensor(zone_return_object, "System Node Relative Humidity", zone, self.create_node(hp.return_air_humidity_sensor, bp.Return_Air_Humidity_Sensor), zone_point_ref)
                    self.add_sensor(zone_return_object, "System Node Mass Flow Rate", zone, self.create_node(hp.return_air_flow_sensor, bp.Return_Air_Flow_Sensor), zone_point_ref)

                zat = self.create_node(hp.air_temp_sensor, bp.Zone_Air_Temperature_Sensor)
                zat.add_tags(['zone'], h_ont)
                self.add_sensor(zone_object.zoneAirNode(), "System Node Temperature", zone, zat, zone_point_ref)

                zarh = self.create_node(hp.air_humidity_sensor, bp.Zone_Air_Humidity_Sensor)
                zarh.add_tags(['zone'], h_ont)
                self.add_sensor(zone_object.zoneAirNode(), "System Node Relative Humidity", zone, zarh, zone_point_ref)

                zathsp = self.create_node(hp.air_temp_sp, bp.Zone_Air_Heating_Temperature_Setpoint)
                zathsp.add_tags(['zone', 'heating'], h_ont)
                self.add_actuator(zone_object.zoneAirNode(), "Zone Temperature Control", "Heating Setpoint", zone, zathsp, zone_point_ref)

                zatcsp = self.create_node(hp.air_temp_sp, bp.Zone_Air_Cooling_Temperature_Setpoint)
                zatcsp.add_tags(['zone', 'cooling'], h_ont)
                self.add_actuator(zone_object.zoneAirNode(), "Zone Temperature Control", "Cooling Setpoint", zone, zatcsp, zone_point_ref)

        self.sync()
        return graphs

    def resolve_plant_loop(self, plant_object):
        plant_loop_name = name_to_id(plant_object.name().get())
        plant = self.get_node_by_name(plant_loop_name)
        if plant is None:
            site = self.G.get_extra('site')
            plant_type = PlantType.plant_type_from_string(plant_loop_name)
            print(plant_type)
            supply_inlet_node = plant_object.supplyInletNode()
            supply_outlet_object = plant_object.supplyOutletNode()
            demand_outlet_object = plant_object.demandOutletNode()

            plant_context = self.G.get_downstream_subgraph(supply_inlet_node.name().get(), stop_at_nodes=plant_object.name().get())

            if plant_type == PlantType.HOT_WATER:
                plant = self.create_node(he.hot_water_plant, bs.Hot_Water_System, name=plant_loop_name)
            elif plant_type == PlantType.CHILLED_WATER:
                plant = self.create_node(he.chilled_water_plant, bs.Chilled_Water_System, name=plant_loop_name)
            elif plant_type == PlantType.CONDENSER_WATER:
                plant = self.create_node(he.chilled_water_plant, bs.Condenser_Water_System, name=plant_loop_name)

            plant_context.set_extra('plant', plant)
            plant.add_relationship(site_ref, site)

            if plant_type == PlantType.HOT_WATER:
                self.add_sensor(demand_outlet_object, "System Node Temperature", plant, self.create_node(hp.leaving_hot_water_temp_sensor, bp.Hot_Water_Return_Temperature_Sensor), point_ref)
                self.add_sensor(demand_outlet_object, "System Node Mass Flow Rate", plant, self.create_node(hp.leaving_hot_water_flow_sensor, bp.Return_Water_Flow_Sensor), point_ref)
                self.add_actuator(demand_outlet_object, "System Node Setpoint", "Temperature Setpoint", plant, self.create_node(hp.leaving_hot_water_temp_sp, bp.Leaving_Water_Temperature_Setpoint), point_ref)

                self.add_sensor(supply_outlet_object, "System Node Temperature", plant, self.create_node(hp.entering_hot_water_temp_sensor, bp.Hot_Water_Supply_Temperature_Sensor), point_ref)
                self.add_sensor(supply_outlet_object, "System Node Mass Flow Rate", plant, self.create_node(hp.entering_hot_water_flow_sensor, bp.Supply_Water_Flow_Sensor), point_ref)
                self.add_actuator(supply_outlet_object, "System Node Setpoint", "Temperature Setpoint", plant, self.create_node(hp.entering_hot_water_temp_sp, bp.Entering_Water_Temperature_Setpoint), point_ref)
            elif plant_type == PlantType.CHILLED_WATER:
                self.add_sensor(demand_outlet_object, "System Node Temperature", plant, self.create_node(hp.leaving_chilled_water_temp_sensor, bp.Chilled_Water_Return_Temperature_Sensor), point_ref)
                self.add_sensor(demand_outlet_object, "System Node Mass Flow Rate", plant, self.create_node(hp.leaving_chilled_water_flow_sensor, bp.Return_Water_Flow_Sensor), point_ref)
                self.add_actuator(demand_outlet_object, "System Node Setpoint", "Temperature Setpoint", plant, self.create_node(hp.leaving_chilled_water_temp_sp, bp.Leaving_Water_Temperature_Setpoint), point_ref)

                self.add_sensor(supply_outlet_object, "System Node Temperature", plant, self.create_node(hp.entering_chilled_water_temp_sensor, bp.Chilled_Water_Supply_Temperature_Sensor), point_ref)
                self.add_sensor(supply_outlet_object, "System Node Mass Flow Rate", plant, self.create_node(hp.entering_chilled_water_flow_sensor, bp.Supply_Water_Flow_Sensor), point_ref)
                self.add_actuator(supply_outlet_object, "System Node Setpoint", "Temperature Setpoint", plant, self.create_node(hp.entering_chilled_water_temp_sp, bp.Entering_Water_Temperature_Setpoint), point_ref)

            nx.nx_pydot.to_pydot(plant_context).write_png(f"{plant_loop_name}.png")

            supply_equip_context = plant_context.get_downstream_subgraph(plant_object.supplySplitter(), stop_at_types=[openstudio.IddObjectType('OS:Connector:Mixer')])
            nx.nx_pydot.to_pydot(supply_equip_context).write_png(f'{plant_loop_name}_supply_equip.png')

            flow_sensor_tagging = {
                PlantType.HOT_WATER: [hp.hot_water_flow_sensor, bp.Hot_Water_Flow_Sensor],
                PlantType.CHILLED_WATER: [hp.chilled_water_flow_sensor, bp.Water_Flow_Sensor]
            }
            for node in plant_context.get_nodes_by_type(openstudio.IddObjectType("OS:Pump:VariableSpeed")):
                pump_object = plant_context.get_object_from_node(node)
                pump = self.create_node(he.pump_motor, be.Pump_VFD, name=node)
                pump.add_relationship(equip_ref, plant)
                self.add_sensor(pump_object, "Pump Electricity Rate", pump, self.create_node(shrap.ElecPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)

                self.add_sensor(pump_object, "Pump Mass Flow Rate", pump, self.create_node(*flow_sensor_tagging[plant_type]), point_ref)

            for node in plant_context.get_nodes_by_type(openstudio.IddObjectType("OS:Pump:ConstantSpeed")):
                pump_object = plant_context.get_object_from_node(node)
                pump = self.create_node(he.pump_motor, be.Water_Pump, name=node)
                pump.add_relationship(equip_ref, plant)
                self.add_sensor(pump_object, "Pump Electricity Rate", pump, self.create_node(shrap.ElecPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)
                self.add_sensor(pump_object, "Pump Mass Flow Rate", pump, self.create_node(*flow_sensor_tagging[plant_type]), point_ref)

            for node in plant_context.get_nodes_by_type(openstudio.IddObjectType("OS:Boiler:HotWater")):
                boiler_object = plant_context.get_object_from_node(node)
                boiler = self.create_node(he.boiler, be.Boiler, name=node)
                boiler_inlet_object = boiler_object.inletModelObject().get()
                boiler_outlet_object = boiler_object.outletModelObject().get()
                boiler.add_relationship(equip_ref, plant)
                self.add_sensor(boiler_object, "Boiler Natural Gas Rate", boiler, self.create_node(shrap.GasEnergySensorShape, bp.Energy_Sensor), point_ref)
                self.add_sensor(boiler_object, "Boiler Heating Rate", boiler, self.create_node(shrap.HeatingCapacitySensorShape, bp.Thermal_Power_Sensor), point_ref)

                self.add_sensor(boiler_inlet_object, "System Node Temperature", boiler, self.create_node(hp.entering_hot_water_temp_sensor, bp.Hot_Water_Return_Temperature_Sensor), point_ref)
                self.add_sensor(boiler_inlet_object, "System Node Mass Flow Rate", boiler, self.create_node(hp.entering_hot_water_flow_sensor, bp.Return_Water_Flow_Sensor), point_ref)
                self.add_actuator(boiler_inlet_object, "System Node Setpoint", "Temperature Setpoint", boiler, self.create_node(hp.entering_hot_water_temp_sp, bp.Entering_Water_Temperature_Setpoint), point_ref)

                self.add_sensor(boiler_outlet_object, "System Node Temperature", boiler, self.create_node(hp.leaving_hot_water_temp_sensor, bp.Hot_Water_Supply_Temperature_Sensor), point_ref)
                self.add_sensor(boiler_outlet_object, "System Node Mass Flow Rate", boiler, self.create_node(hp.leaving_hot_water_flow_sensor, bp.Supply_Water_Flow_Sensor), point_ref)
                self.add_actuator(boiler_outlet_object, "System Node Setpoint", "Temperature Setpoint", boiler, self.create_node(hp.leaving_hot_water_temp_sp, bp.Leaving_Water_Temperature_Setpoint), point_ref)

            for node in plant_context.get_nodes_by_type(openstudio.IddObjectType("OS:Chiller:Electric:EIR")):
                chiller_object = plant_context.get_object_from_node(node)
                chiller = self.create_node(he.chiller, be.Chiller, name=node)
                chiller_inlet_object = chiller_object.supplyInletModelObject().get()
                chiller_outlet_object = chiller_object.supplyOutletModelObject().get()
                chiller.add_relationship(equip_ref, plant)
                self.add_sensor(chiller_object, "Chiller Electricity Rate", chiller, self.create_node(shrap.ElecPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)
                self.add_sensor(chiller_object, "Chiller Evaporator Cooling Rate", chiller, self.create_node(shrap.CoolingCapacitySensorShape, bp.Thermal_Power_Sensor), point_ref)

                self.add_sensor(chiller_inlet_object, "System Node Temperature", chiller, self.create_node(hp.entering_chilled_water_temp_sensor, bp.Chilled_Water_Return_Temperature_Sensor), point_ref)
                self.add_sensor(chiller_inlet_object, "System Node Mass Flow Rate", chiller, self.create_node(hp.entering_chilled_water_flow_sensor, bp.Return_Water_Flow_Sensor), point_ref)
                self.add_actuator(chiller_inlet_object, "System Node Setpoint", "Temperature Setpoint", chiller, self.create_node(hp.entering_chilled_water_temp_sp, bp.Entering_Water_Temperature_Setpoint), point_ref)

                self.add_sensor(chiller_outlet_object, "System Node Temperature", chiller, self.create_node(hp.leaving_chilled_water_temp_sensor, bp.Chilled_Water_Supply_Temperature_Sensor), point_ref)
                self.add_sensor(chiller_outlet_object, "System Node Mass Flow Rate", chiller, self.create_node(hp.leaving_chilled_water_flow_sensor, bp.Supply_Water_Flow_Sensor), point_ref)
                self.add_actuator(chiller_outlet_object, "System Node Setpoint", "Temperature Setpoint", chiller, self.create_node(hp.leaving_chilled_water_temp_sp, bp.Leaving_Water_Temperature_Setpoint), point_ref)

            for node in supply_equip_context.get_nodes_by_type(openstudio.IddObjectType("OS:Pipe:Adiabatic")):
                pipe_object = plant_context.get_object_from_node(node)
                pipe_inlet_object = pipe_object.inletModelObject().get()
                if plant_type == PlantType.CHILLED_WATER:
                    self.add_sensor(pipe_inlet_object, "System Node Mass Flow Rate", plant, self.create_node(hp.bypass_chilled_water_flow_sensor, bp.Water_Flow_Sensor), point_ref)
                elif plant_type == PlantType.HOT_WATER:
                    self.add_sensor(pipe_inlet_object, "System Node Mass Flow Rate", plant, self.create_node(hp.bypass_hot_water_flow_sensor, bp.Water_Flow_Sensor), point_ref)

        return plant


    def resolve_terminals(self, context, multi_zones):
        ahu = context.get_extra('ahu')
        zone = context.get_extra('zone')
        reheat_coil_object = None
        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:AirTerminal:SingleDuct:VAV:Reheat")):
            terminal_object = context.get_object_from_node(node)
            terminal_inlet_object = terminal_object.inletModelObject().get()

            terminal = self.create_node(he.vav, be.RVAV, name=node)
            reheat_coil_object = terminal_object.reheatCoil()

        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:AirTerminal:SingleDuct:ConstantVolume:NoReheat")):
            terminal_object = context.get_object_from_node(node)
            terminal_inlet_object = terminal_object.inletModelObject().get()

            terminal = self.create_node(he.cav, be.CAV, name=node)

        terminal.add_relationship(air_ref, ahu)
        terminal.add_relationship(space_ref, zone)
        zone.add_relationship(air_ref, terminal)
        damper_position_command = self.create_node(shrap.DamperCmdShape, bp.Damper_Position_Command)
        self.add_empty_actuator(terminal_object, "Zone Air Terminal VAV Damper Position", terminal, damper_position_command, point_ref)
        self.add_empty_actuator(terminal_object, "Zone Air Terminal Minimum Air Flow Fraction", terminal, self.create_node(shrap.MinAirFractionSetpointShape, bp.Min_Position_Setpoint_Limit), point_ref)

        context.set_extra('terminal', terminal)
        if multi_zones:
            self.add_sensor(terminal_inlet_object, "System Node Temperature", terminal, self.create_node(hp.discharge_air_temp_sensor, bp.Discharge_Air_Temperature_Sensor), zone_point_ref)
            self.add_sensor(terminal_inlet_object, "System Node Mass Flow Rate", terminal, self.create_node(hp.discharge_air_flow_sensor, bp.Discharge_Air_Flow_Sensor), zone_point_ref)
            self.add_sensor(terminal_inlet_object, "System Node Relative Humidity", terminal, self.create_node(hp.discharge_air_humidity_sensor, bp.Discharge_Air_Humidity_Sensor), zone_point_ref)

        if reheat_coil_object:
            self.add_reheat_coil(context, reheat_coil_object, terminal_object)

    def add_reheat_coil(self, context, reheat_coil_object, terminal_object):
        terminal_outlet_object = terminal_object.outletModelObject().get()
        terminal = context.get_extra('terminal')
        zone = context.get_extra('zone')
        idd_type = reheat_coil_object.iddObjectType()
        if idd_type == openstudio.IddObjectType("OS:Coil:Heating:Electric"):
            coil = self.create_node(shrap.ElecHeatingCoilShape, be.Heating_Coil, model_object=reheat_coil_object)
            self.add_sensor(reheat_coil_object, "Heating Coil Electricity Rate", coil, self.create_node(shrap.ElecHeatingPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)
        elif idd_type == openstudio.IddObjectType("OS:Coil:Heating:Water"):
            reheat_coil_object = cast_openstudio_object(reheat_coil_object)
            water_inlet_object = reheat_coil_object.waterInletModelObject().get()
            water_outlet_object = reheat_coil_object.waterOutletModelObject().get()
            coil = self.create_node(shrap.WaterHeatingCoilShape, be.Hot_Water_Coil, model_object=reheat_coil_object)
            plant_loop_object = reheat_coil_object.plantLoop().get()
            plant = self.resolve_plant_loop(plant_loop_object)
            coil.add_relationship(MetaRef(hrefs.hotWaterRef, brefs.isFedBy), plant)

            points = []
            points.append(self.add_sensor(water_inlet_object, "System Node Temperature", coil, self.create_node(hp.entering_hot_water_temp_sensor, bp.Hot_Water_Supply_Temperature_Sensor), point_ref))
            points.append(self.add_sensor(water_inlet_object, "System Node Mass Flow Rate", coil, self.create_node(hp.entering_hot_water_flow_sensor, bp.Supply_Water_Flow_Sensor), point_ref))
            points.append(self.add_actuator(water_inlet_object, "System Nonde Setpoint", "Temperature Setpoint", coil, self.create_node(hp.entering_hot_water_temp_sp, bp.Entering_Water_Temperature_Setpoint), point_ref))

            points.append(self.add_sensor(water_outlet_object, "System Node Temperature", coil, self.create_node(hp.leaving_hot_water_temp_sensor, bp.Hot_Water_Return_Temperature_Sensor), point_ref))
            points.append(self.add_sensor(water_outlet_object, "System Node Mass Flow Rate", coil, self.create_node(hp.leaving_hot_water_flow_sensor, bp.Return_Water_Flow_Sensor), point_ref))
            points.append(self.add_actuator(water_outlet_object, "System Nonde Setpoint", "Temperature Setpoint", coil, self.create_node(hp.leaving_hot_water_temp_sp, bp.Leaving_Water_Temperature_Setpoint), point_ref))
            for point in points:
                point.add_relationship(space_ref, zone)

        coil.add_tags(['reheats'], h_ont)
        coil.add_relationship(equip_ref, terminal)
        self.add_sensor(terminal_outlet_object, "System Node Temperature", coil, self.create_node(hp.discharge_air_temp_sensor, bp.Discharge_Air_Temperature_Sensor), point_ref)
        self.add_sensor(terminal_outlet_object, "System Node Relative Humidity", coil, self.create_node(hp.discharge_air_humidity_sensor, bp.Discharge_Air_Humidity_Sensor), point_ref)

    def resolve_supply_fans(self, context):
        ahu = context.get_extra('ahu')
        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Fan:VariableVolume")):
            fan = self.create_node(shrap.VAVFanShape, be.Fan_VFD, name=node)
            fan.add_tags(['discharge'], h_ont)
            fan.add_relationship(equip_ref, ahu)
            self.add_supply_fan_points(fan, context.get_object_from_node(node))

        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Fan:ConstantVolume")):
            fan = self.create_node(shrap.CAVFanShape, be.Discharge_Fan, name=node)
            fan.add_tags(['discharge'], h_ont)
            fan.add_relationship(equip_ref, ahu)
            self.add_supply_fan_points(fan, context.get_object_from_node(node))

    def add_supply_fan_points(self, fan, fan_object):
        self.add_sensor(fan_object, "Fan Electricity Rate", fan, self.create_node(shrap.ElecPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)
    
    def resolve_supply_coils(self, context: OpenStudioGraph):
        ahu = context.get_extra('ahu')
        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Coil:Heating:Gas")):
            coil_object = context.get_object_from_node(node)
            coil = self.create_node(shrap.GasHeatingCoilShape, be.Heating_Coil, name=node)
            coil.add_relationship(equip_ref, ahu)

            self.add_sensor(coil_object, "Heating Coil NaturalGas Rate", coil, self.create_node(shrap.GasEnergySensorShape, bp.Energy_Sensor), point_ref)
            self.add_supply_coil_points(coil, coil_object, heating=True)

        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Coil:Heating:Electric")):
            coil_object = context.get_object_from_node(node)
            coil = self.create_node(shrap.ElecHeatingCoilShape, be.Heating_Coil, name=node)
            coil.add_relationship(equip_ref, ahu)

            self.add_sensor(coil_object, "Heating Coil Electricity Rate", coil, self.create_node(shrap.ElecPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)
            self.add_supply_coil_points(coil, coil_object)

        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Coil:Cooling:DX:SingleSpeed")):
            print("single speed DX Coil")
            coil_object = context.get_object_from_node(node)
            coil = self.create_node(shrap.OSDXCoolingCoilShape, be.Cooling_Coil, name=node)
            coil.add_relationship(equip_ref, ahu)
            self.add_sensor(coil_object, "Cooling Coil Electricity Rate", coil, self.create_node(shrap.ElecPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)
            self.add_supply_coil_points(coil, coil_object, heating=False)

        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Coil:Cooling:DX:TwoSpeed")):
            coil_object = context.get_object_from_node(node)
            coil = self.create_node(shrap.OSDXCoolingCoilShape, be.Cooling_Coil, name=node)
            coil.add_relationship(equip_ref, ahu)
            self.add_sensor(coil_object, "Cooling Coil Electricity Rate", coil, self.create_node(shrap.ElecPowerSensorShape, bp.Electrical_Power_Sensor), point_ref)
            self.add_supply_coil_points(coil, coil_object, heating=False)

        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Coil:Heating:Water")):
            coil_object = context.get_object_from_node(node)
            water_inlet_object = coil_object.waterInletModelObject().get()
            water_outlet_object = coil_object.waterOutletModelObject().get()
            coil = self.create_node(shrap.WaterHeatingCoilShape, be.Hot_Water_Coil, model_object=coil_object)
            plant_loop_object = coil_object.plantLoop().get()
            plant = self.resolve_plant_loop(plant_loop_object)
            coil.add_relationship(MetaRef(hrefs.hotWaterRef, brefs.isFedBy), plant)

            self.add_sensor(water_inlet_object, "System Node Temperature", ahu, self.create_node(hp.entering_hot_water_temp_sensor, bp.Hot_Water_Supply_Temperature_Sensor), point_ref)
            self.add_sensor(water_inlet_object, "System Node Mass Flow Rate", ahu, self.create_node(hp.entering_hot_water_flow_sensor, bp.Supply_Water_Flow_Sensor), point_ref)
            self.add_actuator(water_inlet_object, "System Node Setpoint", "Temperature Setpoint", ahu, self.create_node(hp.entering_hot_water_temp_sp, bp.Supply_Hot_Water_Temperature_Setpoint), point_ref)

            self.add_sensor(water_outlet_object, "System Node Temperature", ahu, self.create_node(hp.leaving_hot_water_temp_sensor, bp.Hot_Water_Return_Temperature_Sensor), point_ref)
            self.add_sensor(water_outlet_object, "System Node Mass Flow Rate", ahu, self.create_node(hp.leaving_hot_water_flow_sensor, bp.Return_Water_Flow_Sensor), point_ref)
            self.add_actuator(water_outlet_object, "System Node Setpoint", "Temperature Setpoint", ahu, self.create_node(hp.leaving_hot_water_temp_sp, bp.Leaving_Water_Temperature_Setpoint), point_ref)
            self.add_supply_coil_points(coil, coil_object)

        for node in context.get_nodes_by_type(openstudio.IddObjectType("OS:Coil:Cooling:Water")):
            coil_object = context.get_object_from_node(node)
            water_inlet_object = coil_object.waterInletModelObject().get()
            water_outlet_object = coil_object.waterOutletModelObject().get()
            coil = self.create_node(shrap.WaterCoolingCoilShape, be.Chilled_Water_Coil, model_object=coil_object)
            plant_loop_object = coil_object.plantLoop().get()
            plant = self.resolve_plant_loop(plant_loop_object)
            coil.add_relationship(MetaRef(hrefs.chilledWaterRef, brefs.isFedBy), plant)

            self.add_sensor(water_inlet_object, "System Node Temperature", ahu, self.create_node(hp.entering_chilled_water_temp_sensor, bp.Chilled_Water_Supply_Temperature_Sensor), point_ref)
            self.add_sensor(water_inlet_object, "System Node Mass Flow Rate", ahu, self.create_node(hp.entering_chilled_water_flow_sensor, bp.Supply_Water_Flow_Sensor), point_ref)
            self.add_actuator(water_inlet_object, "System Node Setpoint", "Temperature Setpoint", ahu, self.create_node(hp.entering_chilled_water_temp_sp, bp.Supply_Chilled_Water_Temperature_Setpoint), point_ref)

            self.add_sensor(water_outlet_object, "System Node Temperature", ahu, self.create_node(hp.leaving_chilled_water_temp_sensor, bp.Chilled_Water_Return_Temperature_Sensor), point_ref)
            self.add_sensor(water_outlet_object, "System Node Mass Flow Rate", ahu, self.create_node(hp.leaving_chilled_water_flow_sensor, bp.Return_Water_Flow_Sensor), point_ref)
            self.add_actuator(water_outlet_object, "System Node Setpoint", "Temperature Setpoint", ahu, self.create_node(hp.leaving_chilled_water_temp_sp, bp.Leaving_Water_Temperature_Setpoint), point_ref)
            self.add_supply_coil_points(coil, coil_object, heating=False)

    def add_supply_coil_points(self, coil, coil_object, heating=True):
        if hasattr(coil_object, "outletModelObject"):
            outlet_object = cast_openstudio_object(coil_object.outletModelObject().get())
        elif hasattr(coil_object, "airOutletModelObject"):
            outlet_object = cast_openstudio_object(coil_object.airOutletModelObject().get())

        if heating:
            self.add_sensor(coil_object, "Heating Coil Air Heating Rate", coil, self.create_node(shrap.HeatingCapacitySensorShape, bp.Thermal_Power_Sensor), point_ref)
        else:
            self.add_sensor(coil_object, "Cooling Coil Total Cooling Rate", coil, self.create_node(shrap.CoolingCapacitySensorShape, bp.Thermal_Power_Sensor), point_ref)
        
        self.add_sensor(outlet_object, "System Node Temperature", coil, self.create_node(hp.discharge_air_temp_sensor, bp.Discharge_Air_Temperature_Sensor), point_ref)
        self.add_sensor(outlet_object, "System Node Mass Flow Rate", coil, self.create_node(hp.discharge_air_flow_sensor, bp.Discharge_Air_Flow_Sensor), point_ref)
        self.add_sensor(outlet_object, "System Node Relative Humidity", coil, self.create_node(hp.discharge_air_humidity_sensor, bp.Discharge_Air_Humidity_Sensor), point_ref)

    def add_sensor(self, node_object, system_node_property, tasty_parent_object, tasty_object, tasty_relationship):
        name = node_object.name().get() + '_' + system_node_property.replace(' ','_')
        output_variable = openstudio.openstudiomodel.OutputVariable(system_node_property, self.model)
        output_variable.setKeyValue(node_object.name().get())
        output_variable.setReportingFrequency('timestep')
        output_variable.setName(name)

        sensor = openstudio.openstudiomodel.EnergyManagementSystemSensor(self.model, output_variable)
        sensor.setKeyName(str(node_object.handle()))
        sensor.setName(f"EMS_{name}")

        sensor_name = name_to_id(output_variable.name().get())
        tasty_object.set_namespace(self.namespace)
        tasty_object.set_id(sensor_name)
        tasty_object.add_relationship(tasty_relationship, tasty_parent_object)
        tasty_object.sync()
        return tasty_object

    def add_actuator(self, node_object, actuator_component_type, actuator_control_type, tasty_parent_object, tasty_object, tasty_relationship):
        name = name_to_id(node_object.name().get() + ' ' + actuator_control_type)
        actuator  = openstudio.openstudiomodel.EnergyManagementSystemActuator(node_object, actuator_component_type, actuator_control_type)
        actuator.setName(name)

        actuator_name = name_to_id(actuator.name().get())
        tasty_object.set_namespace(self.namespace)
        tasty_object.set_id(actuator_name)
        tasty_object.add_relationship(tasty_relationship, tasty_parent_object)
        tasty_object.sync()
        return tasty_object

    def add_empty_actuator(self, node_object, actuator_name, tasty_parent_object, tasty_object, tasty_relationship):
        name = name_to_id(node_object.name().get() + ' ' + actuator_name)
        tasty_object.set_id(name)
        tasty_object.set_namespace(self.namespace)
        tasty_object.add_relationship(tasty_relationship, tasty_parent_object)
        tasty_object.sync()
        return tasty_object


    def create_node(self, *nodes, name=None, model_object=None) -> 'MetaNode':
        node = MetaNode(*nodes)
        if model_object != None:
            name = name_to_id(model_object.name().get())
        if name != None:
            name = name_to_id(name)
            node.set_id(name)
        node.set_namespace(self.namespace)
        if node in self.nodes:
            print(str(node))
            print(self.nodes[self.nodes.index(node)])
            return self.nodes[self.nodes.index(node)]
        self.register_node(node)
        return node

    def get_node_by_name(self, name):
        for node in self.nodes:
            if node._id == name:
                return node


    def register_node(self, node):
        self.nodes.append(node)
    
    def sync(self):
        for node in self.nodes:
            node.sync()