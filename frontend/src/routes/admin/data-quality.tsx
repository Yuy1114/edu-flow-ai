import { createFileRoute } from "@tanstack/react-router";
import DataQualityPage from "../../pages/DataQualityPage";

export const Route = createFileRoute("/admin/data-quality")({ component: DataQualityPage });
