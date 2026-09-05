import { createFileRoute } from "@tanstack/react-router";
import SimulationPage from "../../pages/SimulationPage";

export const Route = createFileRoute("/admin/simulation")({ component: SimulationPage });
