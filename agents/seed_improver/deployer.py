"""
Self-Deployer

Uploads modified config to GCS and triggers a new Cloud Run revision.
Includes health checking and automatic rollback.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DeployResult:
    """Result of a deploy attempt."""
    status: str = "pending"  # pending | deployed | rolled_back | failed
    revision_id: str = ""
    previous_revision_id: str = ""
    health_check_passed: bool = False
    rolled_back: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "revision_id": self.revision_id,
            "previous_revision_id": self.previous_revision_id,
            "health_check_passed": self.health_check_passed,
            "rolled_back": self.rolled_back,
            "error": self.error,
        }


class SelfDeployer:
    """Deploys config changes via GCS + Cloud Run revision update.

    Flow:
    1. Upload new stage2.yaml to GCS bucket
    2. Update Cloud Run service env var to trigger new revision
    3. Health check the new revision
    4. Rollback on failure (restore old config in GCS + revert revision)
    """

    def __init__(
        self,
        project_id: str = "",
        region: str = "",
        service_name: str = "",
        gcs_bucket: str = "",
        service_url: str = "",
        health_timeout_seconds: int = 120,
    ):
        self.project_id = project_id or os.getenv("GCP_PROJECT", "cryptotrading-485110")
        self.region = region or os.getenv("GCP_REGION", "australia-southeast1")
        self.service_name = service_name or os.getenv("CLOUD_RUN_SERVICE", "kraken-trader")
        self.gcs_bucket = gcs_bucket or os.getenv("GCS_CONFIG_BUCKET", "")
        self.service_url = service_url or os.getenv("SERVICE_URL", "")
        self.health_timeout = health_timeout_seconds

    async def deploy(self, new_yaml_content: str, old_yaml_content: str) -> DeployResult:
        """Deploy a new config version.

        Args:
            new_yaml_content: The updated stage2.yaml content.
            old_yaml_content: The previous stage2.yaml content (for rollback).

        Returns:
            DeployResult with status and details.
        """
        result = DeployResult()

        if not self.gcs_bucket:
            result.status = "failed"
            result.error = "GCS_CONFIG_BUCKET not configured"
            return result

        try:
            # 1. Upload new config to GCS
            logger.info("Uploading new config to gs://%s/stage2.yaml", self.gcs_bucket)
            await self._upload_to_gcs("stage2.yaml", new_yaml_content)

            # 2. Get current revision (for rollback reference)
            result.previous_revision_id = await self._get_current_revision()

            # 3. Trigger new revision by updating env var
            config_version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            logger.info("Triggering new revision with CONFIG_VERSION=%s", config_version)
            new_revision = await self._update_cloud_run_env(config_version)
            result.revision_id = new_revision or config_version

            # 4. Wait for revision to stabilize
            await asyncio.sleep(10)

            # 5. Health check
            logger.info("Running health check on new revision...")
            healthy = await self._health_check()
            result.health_check_passed = healthy

            if healthy:
                result.status = "deployed"
                logger.info("Deploy successful: revision=%s", result.revision_id)
            else:
                # Rollback
                logger.warning("Health check failed, rolling back...")
                await self._rollback(old_yaml_content, result.previous_revision_id)
                result.status = "rolled_back"
                result.rolled_back = True
                result.error = "Health check failed after deploy"

        except Exception as e:
            logger.exception("Deploy failed: %s", e)
            result.status = "failed"
            result.error = str(e)
            # Attempt rollback
            try:
                await self._upload_to_gcs("stage2.yaml", old_yaml_content)
                result.rolled_back = True
            except Exception as rb_err:
                logger.error("Rollback also failed: %s", rb_err)

        return result

    async def _upload_to_gcs(self, blob_name: str, content: str) -> None:
        """Upload content to a GCS bucket."""
        try:
            from google.cloud import storage
            client = storage.Client(project=self.project_id)
            bucket = client.bucket(self.gcs_bucket)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(content, content_type="text/yaml")
            logger.info("Uploaded %s to gs://%s/%s", blob_name, self.gcs_bucket, blob_name)
        except ImportError:
            # Fallback: use GCS JSON API via httpx
            await self._upload_to_gcs_http(blob_name, content)

    async def _upload_to_gcs_http(self, blob_name: str, content: str) -> None:
        """Upload to GCS using the JSON API (no client library needed)."""
        # Use default credentials from metadata server
        token = await self._get_access_token()
        url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/"
            f"{self.gcs_bucket}/o?uploadType=media&name={blob_name}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                content=content.encode(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "text/yaml",
                },
            )
            resp.raise_for_status()
            logger.info("Uploaded %s via GCS HTTP API", blob_name)

    async def _download_from_gcs(self, blob_name: str) -> Optional[str]:
        """Download content from GCS bucket."""
        try:
            from google.cloud import storage
            client = storage.Client(project=self.project_id)
            bucket = client.bucket(self.gcs_bucket)
            blob = bucket.blob(blob_name)
            return blob.download_as_text()
        except ImportError:
            return await self._download_from_gcs_http(blob_name)
        except Exception as e:
            logger.warning("Failed to download from GCS: %s", e)
            return None

    async def _download_from_gcs_http(self, blob_name: str) -> Optional[str]:
        """Download from GCS using the JSON API."""
        token = await self._get_access_token()
        url = (
            f"https://storage.googleapis.com/storage/v1/b/"
            f"{self.gcs_bucket}/o/{blob_name}?alt=media"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                return resp.text
            return None

    async def _get_access_token(self) -> str:
        """Get access token from GCE metadata server (works on Cloud Run)."""
        url = (
            "http://metadata.google.internal/computeMetadata/v1/"
            "instance/service-accounts/default/token"
        )
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, headers={"Metadata-Flavor": "Google"})
            resp.raise_for_status()
            return resp.json()["access_token"]

    async def _get_current_revision(self) -> str:
        """Get the current serving revision name."""
        try:
            token = await self._get_access_token()
            url = (
                f"https://run.googleapis.com/v2/projects/{self.project_id}/"
                f"locations/{self.region}/services/{self.service_name}"
            )
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {token}"}
                )
                resp.raise_for_status()
                data = resp.json()
                # Latest ready revision
                return data.get("latestReadyRevision", "")
        except Exception as e:
            logger.warning("Could not get current revision: %s", e)
            return ""

    async def _update_cloud_run_env(
        self, config_version: str, dgm_variant_id: Optional[int] = None
    ) -> Optional[str]:
        """Update a Cloud Run env var to trigger a new revision."""
        try:
            token = await self._get_access_token()
            url = (
                f"https://run.googleapis.com/v2/projects/{self.project_id}/"
                f"locations/{self.region}/services/{self.service_name}"
            )

            # Get current service config
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {token}"}
                )
                resp.raise_for_status()
                service = resp.json()

            # Update env var in the template
            template = service.get("template", {})
            containers = template.get("containers", [{}])
            if containers:
                envs = containers[0].get("env", [])
                # Update or add CONFIG_VERSION
                found = False
                for env in envs:
                    if env.get("name") == "CONFIG_VERSION":
                        env["value"] = config_version
                        found = True
                        break
                if not found:
                    envs.append({"name": "CONFIG_VERSION", "value": config_version})

                # Update or add DGM_VARIANT_ID if provided
                if dgm_variant_id is not None:
                    found_dgm = False
                    for env in envs:
                        if env.get("name") == "DGM_VARIANT_ID":
                            env["value"] = str(dgm_variant_id)
                            found_dgm = True
                            break
                    if not found_dgm:
                        envs.append({"name": "DGM_VARIANT_ID", "value": str(dgm_variant_id)})

                containers[0]["env"] = envs

            # PATCH the service
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.patch(
                    url,
                    json=service,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                logger.info("Cloud Run service updated, new revision deploying")
                return config_version

        except Exception as e:
            logger.error("Failed to update Cloud Run: %s", e)
            raise

    async def _health_check(self) -> bool:
        """Poll the /health endpoint until healthy or timeout."""
        if not self.service_url:
            logger.warning("No SERVICE_URL configured, skipping health check")
            return True

        deadline = asyncio.get_event_loop().time() + self.health_timeout
        url = f"{self.service_url.rstrip('/')}/health"

        while asyncio.get_event_loop().time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        logger.info("Health check passed: %s", resp.json())
                        return True
            except Exception:
                pass
            await asyncio.sleep(5)

        logger.warning("Health check timed out after %ds", self.health_timeout)
        return False

    async def _rollback(self, old_yaml: str, previous_revision: str) -> None:
        """Rollback: restore old config and route traffic to previous revision."""
        # Restore old config in GCS
        logger.info("Rolling back: restoring old config in GCS")
        await self._upload_to_gcs("stage2.yaml", old_yaml)

        # Trigger another revision with rollback config
        rollback_version = f"rollback-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        try:
            await self._update_cloud_run_env(rollback_version)
            logger.info("Rollback revision triggered: %s", rollback_version)
        except Exception as e:
            logger.error("Rollback revision failed: %s", e)
