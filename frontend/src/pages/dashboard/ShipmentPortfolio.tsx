import { useEffect, useState } from "react";
import {
  fetchDestinationRanking,
  fetchProductRisk,
  fetchTrips,
  type DestinationRanking,
  type ProductRisk,
  type TripSummary,
} from "../../api/client";
import DestinationRankingChart from "../../components/DestinationRankingChart";
import ProductRiskChart from "../../components/ProductRiskChart";
import ShipmentMap from "../../components/ShipmentMap";
import TripsTable from "../../components/TripsTable";

export default function ShipmentPortfolio() {
  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [destinations, setDestinations] = useState<DestinationRanking[]>([]);
  const [productRisk, setProductRisk] = useState<ProductRisk[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchTrips(), fetchDestinationRanking(), fetchProductRisk()])
      .then(([t, d, p]) => {
        setTrips(t);
        setDestinations(d);
        setProductRisk(p);
        setLoadError(null);
      })
      .catch((err) => setLoadError(`Failed to load shipment portfolio: ${err?.message ?? err}`));
  }, []);

  if (loadError) return <div className="error-box">{loadError}</div>;

  return (
    <div>
      <TripsTable trips={trips} />

      <div className="panel-grid" style={{ marginTop: 18 }}>
        <ShipmentMap trips={trips} title="Portfolio Map" />
        <ProductRiskChart products={productRisk} />
      </div>

      <div className="panel-grid">
        <DestinationRankingChart destinations={destinations} />
      </div>
    </div>
  );
}
