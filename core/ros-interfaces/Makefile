DOCKER ?= docker
IMAGE ?= platform-ros-interfaces:jazzy
ROS_BASE_IMAGE ?= docker.io/library/ros:jazzy-ros-base@sha256:31daab66eef9139933379fb67159449944f4e2dcf2e22c2d12cc715f29873e0f
ROS_DOMAIN_ID := 87

ROOT := $(abspath .)
DOCKER_RUN := $(DOCKER) run --rm \
	--read-only \
	--network none \
	--user "$$(id -u):$$(id -g)" \
	--env HOME=/tmp/platform-home \
	--env ROS_DOMAIN_ID=$(ROS_DOMAIN_ID) \
	--env CONTAINER_IMAGE=$(IMAGE)@$$(docker image inspect --format '{{.Id}}' $(IMAGE)) \
	--mount type=bind,src=$(ROOT),dst=/workspace/source,readonly \
	--mount type=bind,src=$(ROOT)/artifacts,dst=/workspace/results \
	--tmpfs /workspace/work:exec,mode=1777,size=4g \
	--tmpfs /tmp:exec,mode=1777,size=512m \
	$(IMAGE)

.PHONY: image clean-results validate build test verify commit

image:
	$(DOCKER) build \
		--build-arg ROS_BASE_IMAGE=$(ROS_BASE_IMAGE) \
		--tag $(IMAGE) \
		--file containers/Dockerfile.jazzy-cyclone .

clean-results:
	find artifacts -mindepth 1 ! -name .gitkeep -delete

validate: image clean-results
	$(DOCKER_RUN) env VERIFY_MODE=validate /opt/platform-ci/container-verify.sh

build: image clean-results
	$(DOCKER_RUN) env VERIFY_MODE=build /opt/platform-ci/container-verify.sh

test: image clean-results
	$(DOCKER_RUN) env VERIFY_MODE=test /opt/platform-ci/container-verify.sh

verify: image clean-results
	$(DOCKER_RUN) env VERIFY_MODE=verify /opt/platform-ci/container-verify.sh

commit: image
	$(DOCKER) run --rm -it \
		--user "$$(id -u):$$(id -g)" \
		--env HOME=/tmp/platform-home \
		--mount type=bind,src=$(ROOT),dst=/workspace/source \
		--tmpfs /tmp:exec,mode=1777,size=512m \
		--workdir /workspace/source \
		$(IMAGE) cz commit
