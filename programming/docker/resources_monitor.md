> 由于国内不能直接拉取`gcr.io`下镜像，所有加个前缀`m.daocloud.io`。

`cadvisor`、`node-exporter`、`prometheus`和`grafana`。`docker compose`配置文件如下：
```bash
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - 9090:9090
    command:
      - --config.file=/etc/prometheus/prometheus.yml
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    depends_on:
      - cadvisor
      - node-exporter
    networks:
      - my-net
  
  cadvisor:
    image: m.daocloud.io/gcr.io/cadvisor/cadvisor:latest
    container_name: cadvisor
    ports:
      - 8080:8080
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    devices:
      - /dev/kmsg
    privileged: true
    networks:
      - my-net

  node-exporter:
    image: quay.io/prometheus/node-exporter:latest
    container_name: node-exporter
    ports:
      - 9100:9100
    command:
      - --path.rootfs=/host
    volumes:
      - /:/host:ro,rslave
    networks:
      - my-net
    
  grafana:
    image: grafana/grafana-enterprise:latest
    container_name: grafana
    ports:
      - 3000:3000
    volumes:
      - ./grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=123456
    depends_on:
      - prometheus
    networks:
      - my-net

networks:
  my-net:
    driver: bridge
```
`prometheus.yml`文件如下：
```bash
global:
  scrape_interval:     1s # By default, scrape targets every 15 seconds.
  evaluation_interval: 1s # Evaluate rules every 15 seconds.

  # Attach these extra labels to all timeseries collected by this Prometheus instance.
  external_labels:
    monitor: 'test-monitor'

rule_files:
#  - 'prometheus.rules.yml'

scrape_configs:
  - job_name: 'prometheus'
    scrape_interval: 1s
    static_configs:
      - targets: ['10.211.55.8:9090']

  - job_name: 'node'
    scrape_interval: 1s
    static_configs:
      - targets:
        - 10.211.55.8:9100

  - job_name: 'docker'
    scrape_interval: 1s
    static_configs:
      - targets:
        - 10.211.55.8:8080
```
