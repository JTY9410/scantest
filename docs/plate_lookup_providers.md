# Korean Vehicle Plate Lookup Providers (차량번호 조회)

This document lists official and commercial Korean APIs that provide vehicle information (including fuel type/연료) from vehicle registration numbers (차량번호).

## Provider Comparison

| Provider | API Type | Request Parameters | Fuel Type Field | Cost/Approval | Source URL |
|----------|----------|-------------------|-----------------|---------------|------------|
| 국토교통부 (MOLIT) | REST | 차량번호, 소유자명 | 연료종류 | Free, requires approval | [data.go.kr](https://www.data.go.kr/data/15000300/openapi.do) |
| CODEF | REST | 차량번호, 소유자명 | 연료 | Commercial, pricing varies | [codef.io](https://codef.io/docs/main) |
| 보험개발원 (KIDI) | REST | 차량번호, 소유자명 | 차량정보.연료 | Requires KIDI membership | [carhistory.or.kr](https://www.carhistory.or.kr) |

## Verified Providers

### 1. 국토교통부 자동차 등록원부 API (MOLIT Vehicle Registration API)

**Status**: Verified from public documentation  
**API URL**: `http://apis.data.go.kr/1613000/CarInformationService/getCarInfo`  
**Documentation**: https://www.data.go.kr/data/15000300/openapi.do

**Request Parameters**:
- `serviceKey`: API key (인증키) from data.go.kr
- `numOfRows`: Results per page (기본값: 10)
- `pageNo`: Page number (기본값: 1)
- `carRegNo`: Vehicle registration number (차량번호) - **REQUIRED**
- `ownerNm`: Owner name (소유자명) - **REQUIRED**
- `carRegYmd`: Vehicle registration date (등록일자, YYYYMMDD) - Optional

**Response Fields**:
```xml
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE</resultMsg>
  </header>
  <body>
    <items>
      <item>
        <carRegNo>12가3456</carRegNo>
        <carMfr>현대자동차</carMfr>
        <carModel>아이오닉5</carModel>
        <modelYear>2021</modelYear>
        <fuelCd>전기</fuelCd>  <!-- 연료종류: 휘발유/경유/LPG/하이브리드/전기/수소 -->
        <engineVolume>0</engineVolume>
        <rearWeight>2220</rearWeight>
      </item>
    </items>
  </body>
</response>
```

**Fuel Type Values** (`fuelCd`):
- `휘발유`: Gasoline
- `경유`: Diesel
- `LPG`: LPG
- `CNG`: Compressed Natural Gas
- `하이브리드`: Hybrid (HEV, may include PHEV)
- `플러그인하이브리드`: Plug-in Hybrid (PHEV)
- `전기`: Electric (BEV)
- `수소` or `연료전지`: Hydrogen Fuel Cell (FCEV)

**Limitations**:
- Requires **owner name** for verification (privacy measure)
- Requires data.go.kr account and API key approval (typically 1-2 business days)
- Free tier has rate limits (1000 requests/day typical)
- XML response format

**Privacy Note**: Owner name is required for request but MUST NOT be stored.

---

### 2. CODEF API

**Status**: Documented but not fully verified  
**API URL**: `https://development.codef.io/`  
**Documentation**: https://codef.io/docs/main

**Request Parameters**:
- Requires CODEF account and authentication
- `organization`: Insurance company or government agency code
- `carNo`: Vehicle registration number (차량번호)
- `userName`: Owner name (소유자명)
- Additional parameters vary by service

**Response Fields**:
- JSON response with vehicle details
- Fuel type field name varies by service endpoint
- Typically includes: maker, model, model_year, displacement, fuel_type

**Limitations**:
- Commercial service, requires contract and pricing negotiation
- Authentication via OAuth 2.0
- API endpoint details require account access

---

### 3. 카히스토리 / 보험개발원 (Car History / KIDI)

**Status**: Verified service exists, API details require membership  
**Service URL**: https://www.carhistory.or.kr  
**API Documentation**: Requires KIDI API membership

**Request Parameters**:
- `차량번호`: Vehicle registration number
- `소유자명`: Owner name
- Additional authentication parameters

**Response Fields**:
- JSON response
- `차량정보.연료`: Fuel type
- Includes insurance history, accident records, recall info

**Limitations**:
- Requires 보험개발원 (Korea Insurance Development Institute) membership
- Primarily focused on insurance/accident history
- API access requires business license and approval
- Commercial pricing

---

## Other Potential Providers (Unverified)

The following services are known to provide vehicle information but their API details could not be verified from public documentation:

- **하이패스**: Toll payment service, may have vehicle info APIs (requires business account)
- **보다 (BODA)**: Used car valuation service (API not publicly documented)
- **SK엔카**: Used car platform (API requires partnership)
- **한국교통안전공단 (KoTSA)**: Vehicle safety info (public APIs focus on recall data, not registration)

## Implementation Recommendations

1. **Primary Provider**: 국토교통부 (MOLIT) API
   - Free, official government data
   - Well-documented
   - Requires owner name for privacy compliance
   - Suitable for user-initiated lookups (user provides owner name)

2. **Fallback/Alternative**: None recommended without user-provided owner name
   - Other providers also require owner name for verification
   - No verified API exists for plate-only lookup

3. **Privacy Requirements**:
   - Owner name must NEVER be stored in database
   - Use only for real-time verification during API request
   - Mask plate numbers in logs and UI (e.g., `12가****`)
   - Store only salted SHA-256 hash of plate number in cache

4. **Rate Limiting**:
   - Implement exponential backoff for retries
   - Cache successful responses (90-day TTL suggested)
   - Respect provider rate limits (typically 1000 req/day for free tier)

## Configuration

Environment variables required:

```bash
# Provider selection
PLATE_LOOKUP_PROVIDER=molit  # Options: molit, codef, none (default)

# MOLIT provider
MOLIT_API_KEY=your_data_go_kr_service_key

# CODEF provider (if implemented)
CODEF_CLIENT_ID=your_client_id
CODEF_CLIENT_SECRET=your_client_secret

# Cache settings
PLATE_LOOKUP_CACHE_TTL_DAYS=90  # Default: 90 days
PLATE_LOOKUP_HASH_SALT=random_salt_generate_on_deploy  # Required for hashing
```

## Security Notes

1. **Never log full plate numbers** - use masked format (e.g., `12가****`)
2. **Never store owner names** - use only for API request verification
3. **Use salted hashes** - plate numbers in cache table must be hashed with deployment-specific salt
4. **Encrypt in transit** - all API requests must use HTTPS
5. **Audit access** - log when plate lookups are performed (with masked plate)

## References

- 국토교통부 Open API: https://www.data.go.kr/data/15000300/openapi.do
- CODEF Documentation: https://codef.io/docs/main
- 카히스토리: https://www.carhistory.or.kr
- data.go.kr 가입 및 API 신청: https://www.data.go.kr/uim/join/joinUsimMain.do
